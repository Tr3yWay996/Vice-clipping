import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {Modal} from './Modal';
import {InlineRename} from './InlineRename';
it('preserves the autofocus rename field without blurring/committing it when a modal opens',async()=>{
 const container=document.createElement('div');document.body.append(container);const root=createRoot(container),cancel=vi.fn(),submit=vi.fn();
 try{
  await act(async()=>root.render(<Modal open title="Rename" onClose={vi.fn()}><InlineRename className="rename" initial="Match" label="Name" onSubmit={submit} onCancel={cancel}/></Modal>));
  const input=container.querySelector('input')!;expect(document.activeElement).toBe(input);expect(input.selectionStart).toBe(0);expect(input.selectionEnd).toBe(5);expect(cancel).not.toHaveBeenCalled();expect(submit).not.toHaveBeenCalled();
 }finally{await act(async()=>root.unmount());container.remove();}
});
