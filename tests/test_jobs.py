import asyncio
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
try:
    import _sandbox  # noqa: F401
except ModuleNotFoundError:
    from tests import _sandbox  # noqa: F401
from vice.jobs import ProcessingQueue
from vice.processing import MediaProcess
from vice.config import Config
from vice.share import ShareServer


async def until(predicate, timeout=3):
    async def check():
        while not predicate():
            await asyncio.sleep(.01)
    await asyncio.wait_for(check(), timeout)


class ProcessingQueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.broadcast = mock.AsyncMock()
        self.queues = []

    def queue(self, runner, **kwargs):
        queue = ProcessingQueue(self.broadcast, runner, path=self.root/'jobs.json', **kwargs)
        self.queues.append(queue)
        return queue

    async def asyncTearDown(self):
        for queue in self.queues:
            await queue.stop()

    async def test_fifo_single_worker_survives_ui_disconnect_and_persists_completed_history(self):
        order = []
        release = asyncio.Event()
        active = 0
        async def run(job):
            nonlocal active
            active += 1
            self.assertEqual(active, 1)
            order.append(job['name'])
            if len(order) == 1:
                await release.wait()
            active -= 1
            return self.root/job['name']
        queue = self.queue(run)
        for name in ['one.mp4','two.mp4','three.mp4']:
            await queue.submit('trim', name, {})
        await until(lambda: len(order) == 1)
        # No connected UI is needed; broadcasting to zero clients is normal.
        self.broadcast.reset_mock()
        release.set()
        await until(lambda: all(job['status'] == 'completed' for job in queue.jobs))
        self.assertEqual(order, ['one.mp4','two.mp4','three.mp4'])
        restored = self.queue(run)
        self.assertEqual([j['status'] for j in restored.snapshot()], ['completed']*3)
        self.assertTrue(all(j['finished_at'] for j in restored.snapshot()))
        self.assertNotIn('payload', restored.snapshot()[0])
        self.assertEqual((self.root/'jobs.json').stat().st_mode & 0o777, 0o600)

    async def test_restart_recovers_queued_marks_active_interrupted_and_removes_partial_output(self):
        async def run(job): return self.root/job['name']
        queue = self.queue(run)
        # Hold the shared resource so submission remains queued.
        await queue.lock.acquire()
        one = await queue.submit('trim', 'one', {})
        await queue.stop()
        queue.lock.release()
        partial = self.root/'unfinished.mp4'
        partial.write_bytes(b'partial')
        queue.jobs.append({**queue.jobs[0], 'id':'interrupted', 'status':'processing', 'started_at':'yesterday',
                           'temporary_paths':[str(partial)]})
        queue.save()
        restored = self.queue(run)
        self.assertEqual(restored.jobs[0]['status'], 'queued')
        self.assertEqual(restored.jobs[1]['status'], 'interrupted')
        self.assertFalse(partial.exists())
        restored.start()
        await until(lambda: restored.jobs[0]['status'] == 'completed')
        self.assertEqual(restored.jobs[1]['status'], 'interrupted')
        self.assertEqual(restored.jobs[0]['id'], one['id'])

    async def test_failed_job_retry_remove_and_duplicate_output_reservation(self):
        succeed = False
        release = asyncio.Event()
        async def run(job):
            await release.wait()
            if not succeed: raise ValueError('test failure')
            return self.root/'result.mp4'
        queue = self.queue(run)
        job = await queue.submit('export','clip',{},output_path=self.root/'result.mp4')
        with self.assertRaises(ValueError):
            await queue.submit('export','other',{},output_path=self.root/'result.mp4')
        release.set()
        await until(lambda: queue.jobs[0]['status'] == 'failed')
        self.assertEqual(queue.jobs[0]['error'], 'test failure')
        succeed = True
        retried = await queue.control(job['id'],'retry')
        self.assertNotEqual(retried['id'], job['id'])
        await until(lambda: queue.jobs[1]['status'] == 'completed')
        await queue.control(job['id'],'remove')
        self.assertEqual(len(queue.jobs),1)

    async def test_real_pause_resume_cancel_controls_only_the_owned_process_group(self):
        marker = self.root/'ticks'
        async def run(job):
            await queue.stage('encode')
            code, error = await queue.process.run([
                sys.executable,'-u','-c',
                'import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile True:\n p.open("a").write("tick\\n");time.sleep(.03)',
                str(marker)])
            if code: raise ValueError(error)
            return marker
        queue = self.queue(run)
        job = await queue.submit('trim','clip',{})
        await until(lambda: marker.exists() and marker.stat().st_size > 10)
        pid = queue.process.proc.pid
        await queue.control(job['id'],'pause')
        await asyncio.sleep(.08)
        size = marker.stat().st_size
        await asyncio.sleep(.15)
        self.assertEqual(marker.stat().st_size,size,'processing continued during pause')
        self.assertEqual(queue.jobs[0]['status'],'paused')
        await queue.control(job['id'],'resume')
        await until(lambda: marker.stat().st_size > size)
        await queue.control(job['id'],'cancel')
        await until(lambda: queue.jobs[0]['status'] == 'cancelled')
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    async def test_queued_pause_resume_cancel_and_stage_controls_are_honest(self):
        release = asyncio.Event()
        async def run(job):
            await queue.stage('saving')
            await release.wait()
            return self.root/'saved'
        queue = self.queue(run)
        await queue.lock.acquire()
        job = await queue.submit('export','clip',{})
        await queue.control(job['id'],'pause')
        queue.lock.release()
        self.assertEqual(queue.jobs[0]['status'],'paused')
        await queue.control(job['id'],'resume')
        await until(lambda: queue.jobs[0]['stage'] == 'saving')
        for action in ['pause','cancel']:
            with self.assertRaises(ValueError): await queue.control(job['id'],action)
        release.set()
        await until(lambda: queue.jobs[0]['status'] == 'completed')

    async def test_stop_interrupts_encode_preserves_pending_queue_and_reaps_child(self):
        async def run(job):
            await queue.process.run([sys.executable,'-c','import time;time.sleep(60)'])
        queue = self.queue(run)
        await queue.submit('export','one',{})
        await queue.submit('export','two',{})
        await until(lambda: queue.process.proc is not None)
        proc = queue.process.proc
        await queue.stop()
        self.assertIsNotNone(proc.returncode)
        self.assertEqual([j['status'] for j in queue.jobs],['interrupted','queued'])

    async def test_repeated_cancel_and_shutdown_do_not_interrupt_owned_child_cleanup(self):
        cleaning, release = asyncio.Event(), asyncio.Event()
        async def run(job):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                await release.wait()
                raise
        queue = self.queue(run)
        job = await queue.submit('export', 'one', {})
        await until(lambda: queue.task is not None)
        first = asyncio.create_task(queue.control(job['id'], 'cancel'))
        await cleaning.wait()
        second = asyncio.create_task(queue.control(job['id'], 'cancel'))
        shutdown = asyncio.create_task(queue.stop())
        await asyncio.sleep(.02)
        self.assertFalse(queue.task.done(), 'A repeated request cancelled cleanup')
        release.set()
        await asyncio.gather(first, second, shutdown)
        self.assertEqual(queue.jobs[0]['status'], 'interrupted')

    async def test_actual_progress_is_persisted_and_does_not_mark_uncommitted_work_complete(self):
        release = asyncio.Event()
        async def run(job):
            await queue.progress(.4, 2.4)
            await release.wait()
            return self.root/'result'
        queue = self.queue(run)
        await queue.submit('export','clip',{})
        await until(lambda: queue.jobs[0]['progress'] == .4)
        stored = json.loads(queue.path.read_text())['jobs'][0]
        self.assertEqual(stored['status'],'processing')
        self.assertEqual(stored['speed'],2.4)
        self.assertIsNone(stored['result_path'])
        self.assertIsNotNone(stored['remaining'])
        release.set()
        await until(lambda: queue.jobs[0]['status'] == 'completed')


class QueueApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_jobs_and_file_paths_are_local_only_and_cannot_escape_clip_index(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'Unicode é space.mp4'
            source.write_bytes(b'video')
            cfg=Config();cfg.output.directory=directory
            server=ShareServer(cfg)
            server._clips['clip']=source
            request=mock.Mock(match_info={'slug':'clip'},query={})
            result=json.loads((await server._api_clip_file(request)).text)
            self.assertEqual(result['uri'],source.as_uri())
            request.match_info['slug']='../../etc/passwd'
            from aiohttp import web
            with self.assertRaises(web.HTTPNotFound):await server._api_clip_file(request)
            public={route.resource.canonical for route in server._public_app.router.routes()}
            self.assertFalse(any('/api/' in path for path in public))
            await server._jobs.stop()

    async def test_real_background_trim_preserves_timestamps_and_restores_history_after_restart(self):
        import shutil
        import subprocess
        from vice import jobs
        if not shutil.which('ffmpeg'):
            self.skipTest('FFmpeg is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'Session.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=10:duration=3',
                            '-c:v','libx264','-threads','1','-g','30',str(source)],check=True,timeout=10)
            stamp=1_000_000_000_123_456_789;os.utime(source,ns=(stamp,stamp))
            before=source.read_bytes()
            cfg=Config();cfg.output.directory=directory
            with mock.patch.object(jobs,'JOBS_PATH',root/'jobs.json'):
                server=ShareServer(cfg);server._clips[source.stem]=source
                server._broadcast_clip=mock.AsyncMock()
                request=mock.Mock(match_info={'slug':source.stem})
                request.json=mock.AsyncMock(return_value={'start':.5,'end':2,'copy':True,'background':True})
                response=json.loads((await server._api_trim(request)).text)
                self.assertIn('job_id',response)
                result=await asyncio.wait_for(server._jobs.wait(response['job_id']),10)
                self.assertEqual(result['status'],'completed',result.get('error'))
                output=Path(result['result_path'])
                self.assertEqual(output.stat().st_mtime_ns,stamp)
                self.assertEqual(source.stat().st_mtime_ns,stamp)
                self.assertEqual(source.read_bytes(),before)
                await server._jobs.stop()
                restored=ShareServer(cfg)
                self.assertEqual(restored._jobs.snapshot()[0]['status'],'completed')
                self.assertEqual(restored._jobs.snapshot()[0]['result_path'],str(output))
                await restored._jobs.stop()

    async def test_appearance_preference_persists_and_does_not_request_a_daemon_restart(self):
        from vice import config as config_module
        with tempfile.TemporaryDirectory() as directory:
            cfg=Config();cfg.output.directory=directory
            server=ShareServer(cfg)
            server.apply_config_cb=mock.AsyncMock()
            request=mock.Mock()
            request.json=mock.AsyncMock(return_value={'ui':{'home_side_panel':'images'}})
            with mock.patch.object(config_module,'CONFIG_PATH',Path(directory)/'config.toml'), \
                 mock.patch.object(config_module,'CONFIG_DIR',Path(directory)):
                result=json.loads((await server._api_save_config(request)).text) if hasattr(server,'_api_save_config') else json.loads((await server._api_set_config(request)).text)
            self.assertFalse(result.get('restart_required'))
            self.assertEqual(server.cfg.ui.home_side_panel,'images')
            self.assertIn('images',(Path(directory)/'config.toml').read_text())
            await server._jobs.stop()


class ChildOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_encoder_dies_if_its_daemon_parent_is_killed(self):
        import subprocess
        import psutil
        if not sys.platform.startswith('linux'):
            self.skipTest('Linux parent-death signal')
        with tempfile.TemporaryDirectory() as directory:
            pid_file=Path(directory)/'pid'
            code='''import asyncio,sys\nfrom vice.processing import MediaProcess\nasyncio.run(MediaProcess().run([sys.executable,'-c',"import os,pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)",sys.argv[1]]))'''
            parent=subprocess.Popen([sys.executable,'-c',code,str(pid_file)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            child=None
            try:
                await until(pid_file.exists)
                child=int(pid_file.read_text())
                parent.kill();await asyncio.to_thread(parent.wait)
                def dead():
                    try:return psutil.Process(child).status()==psutil.STATUS_ZOMBIE
                    except psutil.NoSuchProcess:return True
                await until(dead)
            finally:
                if parent.poll() is None:parent.kill();parent.wait()
                if child:
                    try:os.kill(child,signal.SIGKILL)
                    except ProcessLookupError:pass
