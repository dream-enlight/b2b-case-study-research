import copy,unittest
import report_quality,workspace
import test_report_editorial as editorial


class EvidenceKindTableTests(unittest.TestCase):
    def fixture(self):
        md,db,agg,roles=editorial.EditorialCountTests().fixture()
        agg['dimensions']['buying_situations'][1]['semantic_kinds']={'descriptive':{'profile_count':1},'trigger':{'profile_count':1}}
        md=md.replace('| Embedded connectivity | 2 | 50% |','| Embedded connectivity | 1 | 25% |')
        return md,db,agg,roles

    def test_context_uses_descriptive_count_not_all_kinds(self):
        md,db,agg,roles=self.fixture();report_quality.validate(md,db,agg,roles)
        with self.assertRaisesRegex(workspace.WorkspaceError,'expected 1'):
            report_quality.validate(md.replace('| Embedded connectivity | 1 | 25% |','| Embedded connectivity | 2 | 50% |'),db,agg,roles)

    def test_missing_descriptive_kind_does_not_fall_back_to_total(self):
        md,db,agg,roles=self.fixture();agg['dimensions']['buying_situations'][1]['semantic_kinds'].pop('descriptive')
        with self.assertRaisesRegex(workspace.WorkspaceError,'expected 0'):report_quality.validate(md,db,agg,roles)

    def new_tables(self):
        md,db,agg,roles=self.fixture()
        agg['dimensions']['company_characteristics']=[{'name':'International operations','profile_count':2}]
        agg['dimensions']['buying_situations'].append({'name':'Increase conversion','profile_count':3,'semantic_kinds':{'goal':{'profile_count':1},'trigger':{'profile_count':2}}})
        md=md.replace('# Company profiles','International operations: 2 (50%). Increase conversion: 1 (25%).\n# Company profiles',1)
        md=md.replace('# People and stakeholders','\n| Operating characteristic | Profiles | Share |\n|---|---|---|\n| International operations | 2 | 50% |\n\n# People and stakeholders')
        md=md.replace('# Methods and sources','\n| Goal | Profiles | Share |\n|---|---|---|\n| Increase conversion | 1 | 25% |\n\n# Methods and sources')
        return md,db,agg,roles

    def test_characteristic_and_goal_support_overview_claims(self):
        md,db,agg,roles=self.new_tables();report_quality.validate(md,db,agg,roles)

    def test_incorrect_new_table_counts_and_shares_fail(self):
        md,db,agg,roles=self.new_tables()
        for before,after in [('| International operations | 2 | 50% |','| International operations | 3 | 75% |'),
                             ('| Increase conversion | 1 | 25% |','| Increase conversion | 3 | 75% |'),
                             ('| Increase conversion | 1 | 25% |','| Increase conversion | 1 | 50% |')]:
            with self.subTest(after=after),self.assertRaises(workspace.WorkspaceError):report_quality.validate(md.replace(before,after),db,agg,roles)

    def test_unsupported_and_incorrect_overview_claims_fail(self):
        md,db,agg,roles=self.new_tables()
        for bad in [md.replace('International operations: 2 (50%)','International operations: 3 (75%)'),
                    md.replace('Increase conversion: 1 (25%)','Increase conversion: 3 (75%)'),
                    md.replace('Increase conversion: 1 (25%)','Invented category: 1 (25%)')]:
            with self.subTest(),self.assertRaisesRegex(workspace.WorkspaceError,'supporting table row'):report_quality.validate(bad,db,agg,roles)

    def test_duplicate_new_tables_and_unknown_categories_fail(self):
        md,db,agg,roles=self.new_tables()
        duplicate='\n| Goal | Profiles | Share |\n|---|---|---|\n| Increase conversion | 1 | 25% |\n'
        with self.assertRaisesRegex(workspace.WorkspaceError,'duplicate editorial table'):report_quality.validate(md+duplicate,db,agg,roles)
        with self.assertRaisesRegex(workspace.WorkspaceError,'category not found'):report_quality.validate(md.replace('| International operations |','| Invented category |'),db,agg,roles)

    def test_goal_table_does_not_reinterpret_existing_trigger_claim(self):
        md,db,agg,roles=self.new_tables()
        agg['dimensions']['buying_situations'][0]['semantic_kinds']['goal']={'profile_count':1}
        md=md.replace('Company profiles. People involved.','Engineering bottleneck: 2 (50%). Company profiles. People involved.')
        md=md.replace('| Increase conversion | 1 | 25% |','| Increase conversion | 1 | 25% |\n| Engineering bottleneck | 1 | 25% |')
        report_quality.validate(md,db,agg,roles)
        with self.assertRaisesRegex(workspace.WorkspaceError,'supporting table row'):
            report_quality.validate(md.replace('Engineering bottleneck: 2 (50%)','Engineering bottleneck: 3 (75%)'),db,agg,roles)
