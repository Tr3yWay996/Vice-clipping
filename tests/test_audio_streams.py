import unittest
from unittest import mock
from vice.audio_streams import parse_streams, matching_nodes, inspect_streams


class ApplicationAudioIdentityTests(unittest.TestCase):
    def graph(self):
        return [
            {
                "id": 273,
                "info": {
                    "state": "running",
                    "props": {
                        "media.class": "Stream/Output/Audio",
                        "application.name": "FMOD Audio",
                        "application.process.binary": "BeamNG.drive.x64",
                        "application.process.id": 1941044,
                        "node.name": "FMOD Audio",
                        "target.object": "alsa_output.example",
                    },
                    "params": {"huge": "ignored"},
                },
            },
            {
                "id": 221,
                "info": {
                    "props": {
                        "media.class": "Stream/Output/Audio",
                        "application.name": "Zen",
                        "application.process.binary": "zen",
                        "application.process.id": 3655,
                    }
                },
            },
        ]

    def test_beamng_identity_is_not_its_engine_name(self):
        streams = parse_streams(self.graph())
        matches = matching_nodes(
            streams, [{"field": "executable", "mode": "contains", "value": "beamng"}]
        )
        self.assertEqual([s.node_id for s in matches], [273])
        self.assertEqual(matches[0].name, "FMOD Audio")
        self.assertEqual(
            matching_nodes(streams, [{"field": "name", "value": "BeamNG"}]), []
        )

    def test_casefold_exact_and_multiple_instances_and_rules(self):
        graph = self.graph()
        graph.append({"id": 274, "info": graph[0]["info"]})
        streams = parse_streams(graph)
        self.assertEqual(
            [
                s.node_id
                for s in matching_nodes(
                    streams, [{"field": "executable", "value": "BEAMNG.DRIVE.X64"}]
                )
            ],
            [273, 274],
        )
        self.assertEqual(
            len(
                matching_nodes(
                    streams,
                    [
                        {"field": "name", "value": "zen"},
                        {"field": "executable", "mode": "contains", "value": "beamng"},
                    ],
                )
            ),
            3,
        )

    def test_malformed_metadata_and_non_playback_nodes(self):
        self.assertEqual(
            parse_streams(
                [
                    None,
                    {},
                    {"id": "bad", "info": self.graph()[0]["info"]},
                    {"id": 1, "info": {"props": {"media.class": "Audio/Source"}}},
                ]
            ),
            [],
        )
        with self.assertRaises(ValueError):
            parse_streams({})

    def test_empty_broad_or_unvalidated_regex_rules_are_rejected(self):
        for rule in [
            {"value": ""},
            {"field": "pid", "value": "1"},
            {"mode": "regex", "value": ".*"},
        ]:
            with self.assertRaises(ValueError):
                matching_nodes(parse_streams(self.graph()), [rule])

    def test_missing_pipewire_does_not_fabricate_active_sources_or_levels(self):
        with mock.patch("vice.audio_streams.shutil.which", return_value=None):
            result = inspect_streams()
        self.assertEqual(result["applications"], [])
        self.assertTrue(result["application_warning"])
