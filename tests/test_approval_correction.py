import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runner


class ApprovalCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(runner,'RUNS',Path(self.tmp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.base=runner.run_dir('test')
        self.base.mkdir()
        self.state={'company':'Target','approved_providers':['Target','Keep','Remove'],
                    'phase':'paused_error','paused_from':'stage2','pause_reason':'listing validation'}
        runner.save(self.base,self.state)

    def narrow(self):
        runner.narrow_approval(argparse.Namespace(id='test',remove='Remove'))

    def test_preserves_pause_and_checkpoints_with_backup(self):
        path=runner.inventory_path(self.base)
        runner.atomic_json(path,{'Keep':[{'id':'saved'}]})
        original=path.read_bytes()
        self.narrow()
        state=runner.read_state(self.base)
        self.assertEqual(state['approved_providers'],['Target','Keep'])
        for key in ('phase','paused_from','pause_reason'):
            self.assertEqual(state[key],self.state[key])
        self.assertEqual(path.read_bytes(),original)
        self.assertTrue((Path(state['approval_corrections'][0]['backup'])/'run.zip').exists())

    def test_rejects_provider_with_saved_discovery(self):
        runner.atomic_json(runner.discovery_path(self.base),{'Remove':{'complete':False}})
        with self.assertRaises(runner.RunError):self.narrow()
        self.assertEqual(runner.read_state(self.base),self.state)

    def test_rejects_publication(self):
        self.state['workspace_sheet']={'id':'native'}
        runner.save(self.base,self.state)
        with self.assertRaises(runner.RunError):self.narrow()
