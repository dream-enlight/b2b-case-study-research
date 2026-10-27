"""Offline synthetic regressions; constructed checkpoints, never model calls."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import analysis_compact as ac
import analysis_pipeline as ap
import report_quality
import report_roles
import runner
import semantic_synthesis as ss
import taxonomy_first as tf
import workspace as ws

FIXTURE=Path(__file__).parent/'fixtures/synthetic_usage_roles.json'


class UsageAndFunctionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.fixture=json.loads(FIXTURE.read_text())
        self.cases=self.fixture['cases'];self.cats=self.fixture['categories']
        self.db={'case_ids':[c['id'] for c in self.cases],'rows':[c['cells'] for c in self.cases],
                 'headers':runner.HEADERS,'sheet':{'url':'https://example.invalid/saved-fixture'},
                 'inventoried':8,'complete':8,'unavailable':0,
                 'provider_counts':{c['cells'][0].split('\n')[0]:sum(x['cells'][0].split('\n')[0]==c['cells'][0].split('\n')[0] for x in self.cases) for c in self.cases}}
        self.db['sha256']=ws.digest(self.db);runner.atomic_json(self.base/'finalized_sheet.json',self.db)
        ac.save_registry(self.base,self.db,{'database_sha256':self.db['sha256'],'taxonomy_first':True,
            'categories':self.cats,'legacy_case_ids':[],'legacy_map':{d:{} for d in ac.DIMS}},runner.atomic_json)
        self.state={'phase':'stage4','jobs':{},'analysis_policy':dict(tf.POLICY)}

    def cat(self,dim,name):
        return next(k for k,c in self.cats.items() if c['dimension']==dim and c['name']==name)

    def observation(self,dim,name,col,quote,kind,**extra):
        return dict(cat=self.cat(dim,name),cell=col,quote=quote,kind=kind,
                    strength='unclear' if name==tf.UNKNOWN else 'explicit',**extra)

    def records(self):
        usages={
            'a000000000000001':('Reliable contextual app routing','invitation links carry codes to signup'),
            'a000000000000002':('Open data and stack interoperability','integrated Reporting Metrics API cohort ROI into internal BI'),
            'a000000000000003':('Reliable contextual app routing','Email routing personalized store/app CTAs and linked existing users directly to promoted features'),
            'a000000000000004':('Trustworthy unified attribution','Uses Example Measurement for attribution and acquisition across paid and organic channels.')}
        result=[]
        for c in self.cases:
            cid=c['id'];obs=[]
            for dim in ac.DIMS:
                if dim=='company_category':
                    name=self.cats[c['company_cat']]['name'];quote='' if name==tf.UNKNOWN else c['cells'][3]
                    obs.append(self.observation(dim,name,3,quote,'uncertain' if name==tf.UNKNOWN else 'descriptive'))
                elif dim=='selection_requirements' and cid in usages:
                    name,quote=usages[cid];obs.append(self.observation(dim,name,4,quote,'descriptive',detail='Documented use; original selection reason unavailable.'))
                elif dim=='selection_requirements' and cid=='a000000000000005':
                    obs.append(self.observation(dim,'Open data and stack interoperability',4,
                        'Required reliable, scalable, cost-efficient cross-platform links integrated with attribution.',
                        'requirement'))
                elif dim=='stakeholders':
                    for original in c['stakeholders']:
                        ref=original['evidence_ref'];quote=c['cells'][ref['cell']][ref['start']:ref['end']]
                        obs.append(self.observation(dim,self.cats[original['cat']]['name'],ref['cell'],quote,
                            original['kind'],people=original.get('people',[]),involvement=original.get('involvement',''),
                            **({'detail':original['detail']} if 'detail' in original else {})))
                else:obs.append(self.observation(dim,tf.UNKNOWN,3 if dim=='company_characteristics' else 4,'','uncertain'))
            # The connectivity fixture's stated integration need and the game fixture's documented API use
            # share a category but must retain different profile unions.
            if cid=='a000000000000002':
                obs.append(self.observation('buying_situations','Other',4,
                    'Reported processing time fell after automation.','outcome',
                    detail='Reported ROI result; original purchase motivation unknown.'))
            if cid=='a000000000000003':
                obs.append(self.observation('buying_situations','Other',4,
                    'Needed actionable email-performance insights','goal',detail='Email performance goal.'))
            result.append({'id':cid,'anonymous':False,'observations':obs})
        return result

    def save(self):
        records=self.records()
        for i in range(0,len(records),5):
            batch=records[i:i+5];manifest={'run_dir':str(self.base),'database_sha256':self.db['sha256'],
                'case_ids':[r['id'] for r in batch],'key':'offline'+str(i),'checkpoint_group_size':5}
            ac.checkpoint(manifest,{'records':batch},runner.atomic_json)

    @staticmethod
    def markdown(ctx):
        from fake_report import markdown
        return markdown(ctx)

    def execute(self):
        self.save();calls=[]
        def invoke(base,state,stage,key,ctx,*args):
            self.assertEqual(ctx['analysis_task'],'global_synthesis_report');calls.append(ctx)
            return {'markdown':self.markdown(ctx)}
        api=SimpleNamespace(invoke=invoke,atomic_json=runner.atomic_json,save=lambda *a:None,checkpoint_job=lambda *a:None)
        ap._fresh_calls=0
        # Existing Other-review stage is an offline fixture; it does not alter
        # these observations or invoke a model. All production aggregation and
        # report acceptance code runs unmocked.
        with patch.object(tf,'review_other',return_value={}):md=tf.execute(api,self.base,self.state,self.db,1,'never-launched')
        agg=json.loads((tf.home(self.base,self.db)/'aggregation.json').read_text())
        return md,agg,calls

    def test_saved_workflows_reach_kind_specific_frequencies_and_report(self):
        md,agg,calls=self.execute();self.assertEqual(len(calls),1)
        self.assertTrue(agg['selection_evidence_kinds'])
        caps=agg['dimensions']['selection_requirements']
        for cid,fragment in [('a000000000000001','invitation links'),('a000000000000002','Metrics API'),
                             ('a000000000000003','Email routing'),('a000000000000004','paid and organic')]:
            observations=[o for n in caps for o in n['observations'] if o['case_id']==cid and fragment in o['evidence']]
            self.assertTrue(observations,cid);self.assertTrue(all(o['semantic_kind']=='descriptive' for o in observations))
        api=next(n for n in caps if n['name']=='Open data and stack interoperability')
        self.assertEqual(api['profile_count'],2)
        self.assertEqual(api['semantic_kinds']['requirement']['profile_count'],1)
        self.assertEqual(api['semantic_kinds']['descriptive']['profile_count'],1)
        self.assertIn('Documented use: Open data and stack interoperability | 1 |',md)
        self.assertFalse(any(n['semantic_kinds'].get('trigger') for n in agg['dimensions']['buying_situations']))
        mixed=next(n for n in agg['dimensions']['buying_situations'] if n['name']=='Other')
        self.assertEqual(mixed['profile_count'],2)
        self.assertEqual(mixed['semantic_kinds']['outcome']['profile_count'],1)
        self.assertIn('| Other | 1 | 12.5% |',md)
        bad_outcome=md.replace('| Other | 1 | 12.5% |','| Other | 2 | 25% |')
        with self.assertRaises(ws.WorkspaceError):report_quality.validate(bad_outcome,self.db,agg,report_roles.derive(self.db,agg))
        for bad in [md.replace('Documented use: Open data and stack interoperability | 1 | 12.5%',
                               'Documented use: Open data and stack interoperability | 2 | 25%'),
                    '\n'.join(line for line in md.splitlines() if not line.startswith('| Documented use: Reliable contextual app routing')),
                    md.replace('Documented use: Open data and stack interoperability','Open data and stack interoperability')]:
            with self.assertRaises(ws.WorkspaceError):report_quality.validate(bad,self.db,agg,report_roles.derive(self.db,agg),require_overview=True)

    def test_explicit_functions_and_unknown_people_share_one_counting_authority(self):
        md,agg,calls=self.execute();roles=report_roles.derive(self.db,agg);groups={g['group']:g for g in roles['groups']}
        self.assertEqual(agg['stakeholder_coverage'],report_roles.coverage(roles))
        self.assertEqual(calls[0]['stakeholder_coverage'],agg['stakeholder_coverage'])
        def present(group,cid):return any(e['case_id']==cid for e in groups[group]['evidence'])
        self.assertTrue(present('Marketing / growth','a000000000000005'))
        self.assertTrue(present('Marketing / growth','a000000000000006'))
        self.assertTrue(present('Marketing / growth','a000000000000007'))
        self.assertTrue(present('Product leadership / management','a000000000000007'))
        identified={p for g in roles['groups'] for p in g['profile_ids']}
        index=ap.profile_index(self.db,ac.records(self.base,self.db))['case_to_profile']
        for cid in ['a000000000000001','a000000000000008','a000000000000004']:self.assertNotIn(index[cid],identified)
        self.assertEqual(roles['profiles_with_named_people'],8)
        self.assertEqual(roles['profiles_with_recognized_titles'],5)
        bad=md.replace('Identified function profiles: 5','Identified function profiles: 8')
        with self.assertRaisesRegex(ws.WorkspaceError,'functional coverage'):
            report_quality.validate(bad,self.db,agg,roles,require_overview=True)
        for n in agg['dimensions']['stakeholders']:
            if n['name'] in ['Other','Explicit evaluation and selection participation']:
                self.assertFalse(n['countable_function'])

    def test_titles_are_not_inferred_from_activities_or_other_people(self):
        cells=['Ada, Team Lead, describes working with a Marketing Manager.',
               'Ben, UA Manager, describes implementation.',
               'Cal, Vice President, explains how an engineer helped.',
               'Dan, author, quotes a CEO.',
               'Eve, CMO, testimonial only.']
        db={'case_ids':list('abcde'),'rows':[['','',c,'',''] for c in cells]}
        agg={'distinct_profiles':5,'dimensions':{'stakeholders':[{'observations':[
            {'case_id':cid,'profile_id':cid,'people':[person]} for cid,person in zip(db['case_ids'],['Ada','Ben','Cal','Dan','Eve'])]}]}}
        roles=report_roles.derive(db,agg);self.assertEqual(roles['profiles_with_recognized_titles'],2)
        self.assertEqual(roles['named_profiles_without_recognized_titles'],3)

    def test_unknown_role_cannot_create_a_name_missing_from_its_source_cell(self):
        db={'case_ids':['a'],'rows':[['','','No named customer stakeholders.','','']]}
        agg={'distinct_profiles':1,'dimensions':{'stakeholders':[{'observations':[
            {'case_id':'a','profile_id':'a','people':['Invented Name']}]}]}}
        roles=report_roles.derive(db,agg)
        self.assertEqual(roles['profiles_with_named_people'],0)
        self.assertEqual(roles['profiles_with_recognized_titles'],0)

    def test_empty_unknown_is_never_published_as_documented_use(self):
        records=self.records()
        for record in records:
            for obs in record['observations']:
                if self.cats[obs['cat']]['dimension']=='selection_requirements' and self.cats[obs['cat']]['name']==tf.UNKNOWN:
                    obs['kind']='descriptive'  # Malformed semantic kind from a worker.
        with patch.object(self,'records',return_value=records):md,agg,_=self.execute()
        unknown=next(n for n in agg['dimensions']['selection_requirements'] if n['name']==tf.UNKNOWN)
        self.assertNotIn('descriptive',unknown['semantic_kinds'])
        self.assertNotIn('Documented use: '+tf.UNKNOWN,md)
