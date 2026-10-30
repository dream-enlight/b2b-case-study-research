import copy
import hashlib
import unittest
from unittest.mock import patch

import runner
import workspace
import test_efficiency as efficiency


class DiscoveryRecoveryTests(unittest.TestCase):
    setUp=efficiency.EfficiencyTests.setUp
    tearDown=efficiency.EfficiencyTests.tearDown
    cmd=efficiency.EfficiencyTests.cmd
    state=efficiency.EfficiencyTests.state
    fixture=efficiency.EfficiencyTests.fixture
    record=efficiency.EfficiencyTests.record
    result=efficiency.EfficiencyTests.result
    discovery_item=efficiency.EfficiencyTests.discovery_item

    def page(self,deep=25,light=3,cache=True):
        base,_=self.fixture(0);s=self.state();s['phase']='stage2'
        provider='Beta Software';product=runner.provider_scope(base,s,provider)
        key='inventory_beta-software_'+hashlib.sha256(provider.casefold().encode()).hexdigest()[:8]
        cases=[];items=[]
        for i in range(deep+light):
            url=f'https://stories.example.com/saved/{i}'
            c=dict(id=runner.case_id(provider,url),provider=provider,url=url,customer=f'Customer {i}',title=f'Story {i}',competing_product=product,discovery_key=key)
            item=self.discovery_item(c)
            if i==0:item.update(decision='unresolved',record=None)
            if i==1:item.update(decision='excluded',record=None)
            if i>=deep:item.update(reading_depth='lightweight',record=None)
            if i<deep:
                runner.commit_discovered_case(base,s,key,{'approved_provider':provider,'max_cases':100,'competing_product':product},item)
            cases.append(c);items.append(item)
        obj={'cases':items,'has_more':True,'next_cursor':'Remaining listing page 2'}
        runner.atomic_json(runner.discovery_path(base),{provider:{'page':1,'cursor':'','seen_cursors':[],'complete':False}})
        if cache:
            runner.atomic_json(base/'results'/f'{key}.json',obj)
            s['jobs'][key]={'status':'complete','attempts':1,'response_ready':True}
        runner.save(base,s)
        return base,s,key,cases,obj

    def step(self,base,s):
        with patch.object(runner,'codex_call',side_effect=AssertionError('No research calls')),patch.object(workspace,'ensure_sync',return_value=True):
            return runner.discovery_step(base,s,60,'UNUSED')

    def test_modern_cached_page_uses_100_candidates_instead_of_legacy_20(self):
        base,s,key,cases,obj=self.page(deep=0,light=25)
        self.step(base,s)
        self.assertEqual(len(runner.read_json(runner.screening_path(base))),25)
        self.assertEqual(runner.read_json(runner.discovery_path(base))['Beta Software']['page'],2)
        self.assertEqual(s['jobs'][key]['attempts'],1)

    def test_modern_schema_provenance_does_not_enable_legacy_missing_pagination(self):
        base,s,key,cases,obj=self.page(deep=0,light=0)
        obj.pop('has_more');obj.pop('next_cursor')
        runner.atomic_json(base/'results'/f'{key}.json',obj)
        runner.atomic_json(base/'logs'/f'{key}_saved.schema.json',runner.efficient_schema('discover'))
        with self.assertRaisesRegex(runner.RunError,'pagination'):
            self.step(base,s)

    def test_actual_legacy_cache_retains_legacy_candidate_limit(self):
        base,s,key,cases,obj=self.page(deep=0,light=25)
        for c in obj['cases']:c.pop('reading_depth')
        runner.atomic_json(base/'results'/f'{key}.json',obj)
        with self.assertRaisesRegex(runner.RunError,'candidate batch limit'):
            self.step(base,s)

    def test_saved_oversized_page_accounts_in_twenty_case_units_without_rewrites(self):
        base,s,key,cases,obj=self.page(deep=43,light=1)
        preserved={p:p.read_bytes() for p in (base/'research/cases').rglob('*.json')}
        preserved.update({p:p.read_bytes() for p in (base/'extracted.json',base/'results'/f'{key}.json',base/'research/memory.json')})
        ledger_before=runner.read_json(runner.screening_path(base));policy=copy.deepcopy(s['research_policy'])
        recovery=base/'research/discovery_recovery'/f'{key}.json'
        for offset in (20,40,44):
            self.step(base,s)
            self.assertEqual(runner.read_json(recovery)['offset'],offset)
            progress=runner.read_json(runner.discovery_path(base))['Beta Software']
            self.assertEqual(progress['page'],2 if offset==44 else 1)
            self.assertEqual(progress['cursor'],obj['next_cursor'] if offset==44 else '')
        self.assertTrue(all(p.read_bytes()==v for p,v in preserved.items()))
        ledger=runner.read_json(runner.screening_path(base))
        self.assertEqual(len(ledger),44)
        self.assertTrue(all(ledger[cid]==v for cid,v in ledger_before.items()))
        self.assertEqual(len(runner.read_json(base/'extracted.json')),41)
        self.assertEqual(len(runner.read_json(runner.inventory_path(base))['Beta Software']),42)
        self.assertEqual(s['research_policy'],policy)
        self.assertEqual(s['jobs'][key]['attempts'],1)

    def test_interrupted_unit_replay_is_idempotent(self):
        base,s,key,cases,obj=self.page(deep=25,light=1)
        # Crash after accounting, before persisting its offset: replay that unit.
        write=runner.atomic_json
        def crash(path,value):
            if path.parent.name=='discovery_recovery':raise OSError('Synthetic interrupted recovery')
            return write(path,value)
        with patch.object(runner,'atomic_json',side_effect=crash):
            with self.assertRaisesRegex(OSError,'interrupted'):self.step(base,s)
        self.assertEqual(runner.read_json(runner.discovery_path(base))['Beta Software']['page'],1)
        self.step(base,s)
        self.assertEqual(runner.read_json(base/'research/discovery_recovery'/f'{key}.json')['offset'],20)
        # Crash after the final offset, before advancing the cursor.
        def crash_cursor(path,value):
            if path==runner.discovery_path(base) and value['Beta Software']['page']==2:raise OSError('Synthetic cursor interruption')
            return write(path,value)
        with patch.object(runner,'atomic_json',side_effect=crash_cursor):
            with self.assertRaisesRegex(OSError,'cursor'):self.step(base,s)
        snapshots={p:p.read_bytes() for p in (base/'extracted.json',runner.screening_path(base),runner.inventory_path(base))}
        self.step(base,s)
        self.assertEqual(runner.read_json(runner.discovery_path(base))['Beta Software']['page'],2)
        self.assertTrue(all(p.read_bytes()==v for p,v in snapshots.items()))
        self.assertEqual(s['jobs'][key]['attempts'],1)

    def test_missing_late_deep_checkpoint_rejects_before_any_unit_or_cursor(self):
        base,s,key,cases,obj=self.page()
        runner.case_receipt_path(base,s,cases[24]['id']).unlink()
        before={p:p.read_bytes() for p in (runner.discovery_path(base),runner.screening_path(base),base/'extracted.json')}
        with self.assertRaisesRegex(runner.RunError,'complete checkpoint'):self.step(base,s)
        self.assertFalse((base/'research/discovery_recovery').exists())
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))

    def test_corrupt_extraction_screening_or_receipt_rejected(self):
        base,s,key,cases,obj=self.page();c=cases[24];product=c['competing_product']
        paths=[base/'extracted.json',runner.screening_path(base),runner.case_receipt_path(base,s,c['id'])]
        originals={p:p.read_bytes() for p in paths}
        for target in ('extraction','screening','receipt'):
            with self.subTest(target=target):
                for p,data in originals.items():p.write_bytes(data)
                path=paths[('extraction','screening','receipt').index(target)];value=runner.read_json(path)
                if target=='extraction':value[c['id']]['buying_situation']='Changed'
                elif target=='screening':value[c['id']]['evidence']='Changed'
                else:value['committed']=False
                runner.atomic_json(path,value)
                with self.assertRaises(runner.RunError):runner.validate_discovery_recovery(base,s,key,c['provider'],product,obj)

    def test_later_review_of_partial_discovery_is_preserved(self):
        base,s,key,cases,obj=self.page();c=cases[24]
        # Replace synthetic fixture's last receipt with a partial -> review chain.
        runner.case_receipt_path(base,s,c['id']).unlink()
        records=runner.read_json(base/'extracted.json');records.pop(c['id']);runner.atomic_json(base/'extracted.json',records)
        ledger=runner.read_json(runner.screening_path(base));ledger.pop(c['id']);runner.atomic_json(runner.screening_path(base),ledger)
        obj['cases'][24].update(decision='needs_review',record=None)
        item=obj['cases'][24]
        runner.commit_discovered_case(base,s,key,{'approved_provider':c['provider'],'max_cases':100,'competing_product':c['competing_product']},item)
        partial=runner.read_json(runner.screening_path(base))[c['id']]
        runner.commit_case_result(base,s,'later_review',[partial],self.result(c))
        runner.atomic_json(base/'results'/f'{key}.json',obj)
        receipt=runner.case_receipt_path(base,s,c['id']);before=receipt.read_bytes()
        self.step(base,s);self.step(base,s)
        self.assertEqual(receipt.read_bytes(),before)
        self.assertEqual(runner.read_json(runner.screening_path(base))[c['id']]['decision'],'relevant')

    def test_new_oversized_response_is_still_rejected_even_with_checkpoints(self):
        base,s,key,cases,obj=self.page(cache=False)
        with patch.object(runner,'invoke',return_value=obj),patch.object(workspace,'ensure_sync',return_value=True):
            with self.assertRaisesRegex(runner.RunError,'substantive reading budget'):
                runner.discovery_step(base,s,60,'UNUSED')
        self.assertFalse((base/'research/discovery_recovery').exists())

    def test_recovery_manifest_rejects_changed_response_and_lost_accounted_candidate(self):
        base,s,key,cases,obj=self.page(deep=25,light=1);self.step(base,s)
        changed=copy.deepcopy(obj);changed['next_cursor']='Changed continuation'
        runner.atomic_json(base/'results'/f'{key}.json',changed)
        with self.assertRaisesRegex(runner.RunError,'provenance'):self.step(base,s)
        runner.atomic_json(base/'results'/f'{key}.json',obj)
        ledger=runner.read_json(runner.screening_path(base));ledger.pop(cases[0]['id']);runner.atomic_json(runner.screening_path(base),ledger)
        with self.assertRaisesRegex(runner.RunError,'screening mismatch'):
            runner.discovery_recovery_unit(base,s,key,cases[0]['provider'],cases[0]['competing_product'],obj,runner.read_json(runner.discovery_path(base))['Beta Software'])


if __name__=='__main__':unittest.main()
