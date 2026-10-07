"""Strict provenance declarations and v1 model isolation, tested independently."""
from copy import deepcopy
import math
import unittest

from core import ToolValidationError
from tests.test_column_combinations import combination_parameters
from tools.column.combination_input import COMMON_MODEL_SCHEMA, compose_model, validate_combinations
from tools.column.schemas import MODEL_SCHEMA


class CombinationInputTests(unittest.TestCase):
    def rejects(self, parameters, path=None):
        with self.assertRaises(ToolValidationError) as caught:
            validate_combinations(parameters)
        if path is not None:
            self.assertTrue(any(error['path'][:len(path)] == path for error in caught.exception.errors), caught.exception.errors)

    def test_source_id_duplicates_and_all_identity_mismatches(self):
        cases = [('analysis_id', 'OTHER'), ('member_id', 'OTHER'), ('section_id', 'OTHER'),
                 ('combination_id', 'OTHER'), ('force_record_id', 'ROW-1'),
                 ('unit_system', 'SI'), ('same_force_vector', False), ('same_force_vector', 1)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                parameters = combination_parameters()
                parameters['combinations'][1]['source'][field] = value
                self.rejects(parameters, ['parameters', 'combinations', 1, 'source', field])
        parameters = combination_parameters()
        parameters['combinations'][1]['combination_id'] = 'ULS-1'
        parameters['combinations'][1]['source']['combination_id'] = 'ULS-1'
        self.rejects(parameters, ['parameters', 'combinations', 1, 'combination_id'])

    def test_all_required_source_fields_and_actions_are_mandatory(self):
        for parent in ('source', 'actions'):
            for field in combination_parameters()['combinations'][0][parent]:
                with self.subTest(parent=parent, field=field):
                    parameters = combination_parameters()
                    del parameters['combinations'][0][parent][field]
                    self.rejects(parameters, ['parameters', 'combinations', 0, parent])
        parameters = combination_parameters()
        del parameters['model']['effective_length']['analysis_id']
        self.rejects(parameters, ['parameters', 'model', 'effective_length'])

    def test_ids_accept_chinese_and_limits_reject_all_whitespace(self):
        for text in ('柱', '柱'*128):
            parameters = combination_parameters()
            parameters['combinations'][0]['combination_id'] = text
            parameters['combinations'][0]['source']['combination_id'] = text
            validate_combinations(parameters)
        for text in ('', 'a'*129, 'A B', 'A\tB', 'A\n', 'A\r', 'A\u00a0B', 'A\u2003B', 'A\u3000B'):
            with self.subTest(text=repr(text)):
                parameters = combination_parameters()
                parameters['combinations'][0]['combination_id'] = text
                parameters['combinations'][0]['source']['combination_id'] = text
                self.rejects(parameters)

    def test_combination_count_boundaries_and_no_mutation(self):
        for count in (1, 32):
            parameters = combination_parameters(forces=[1200]*count)
            before = deepcopy(parameters)
            validate_combinations(parameters)
            self.assertEqual(parameters, before)
        for count in (0, 33):
            self.rejects(combination_parameters(forces=[1200]*count), ['parameters', 'combinations'])

    def test_nonzero_moments_shear_boolean_nonfinite_missing_gamma_and_extra(self):
        for field in ('Mx_kN_m', 'My_kN_m', 'Vx_kN', 'Vy_kN'):
            for value in (1, -1, True, False):
                with self.subTest(field=field, value=value):
                    parameters = combination_parameters()
                    parameters['combinations'][1]['actions'][field] = value
                    self.rejects(parameters)
        for value in (True, False, math.inf, -math.inf, math.nan, 0, -1):
            parameters = combination_parameters()
            parameters['combinations'][0]['actions']['N_kN'] = value
            self.rejects(parameters)
        for parent in ('model', 'actions', 'source'):
            parameters = combination_parameters()
            target = parameters['model'] if parent == 'model' else parameters['combinations'][0][parent]
            target['unexpected'] = 1
            self.rejects(parameters)
        parameters = combination_parameters()
        parameters['combinations'][0]['actions']['N_includes_gamma0'] = False
        self.rejects(parameters)

    def test_material_and_common_numeric_errors_have_mapped_paths(self):
        for group, field, value in (('materials', 'fc_MPa', 99), ('section', 'b_mm', True),
                                    ('ties', 'diameter_mm', False), ('effective_length', 'l0_mm', math.inf)):
            parameters = combination_parameters()
            parameters['model'][group][field] = value
            self.rejects(parameters)
        parameters = combination_parameters()
        parameters['model']['materials']['fc_MPa'] = 99
        self.rejects(parameters, ['parameters', 'model', 'materials', 'fc_MPa'])
        parameters = combination_parameters()
        parameters['model']['effective_length']['l0_mm'] = 20000
        self.rejects(parameters, ['parameters', 'model', 'effective_length'])

    def test_compose_model_is_deep_copy_preserves_outer_trace_and_v1_schema(self):
        parameters = combination_parameters()
        before = deepcopy(parameters)
        schema_before = deepcopy(MODEL_SCHEMA)
        model = compose_model(parameters, parameters['combinations'][0])
        self.assertNotIn('analysis_id', model['effective_length'])
        self.assertEqual(model['actions'], parameters['combinations'][0]['actions'])
        model['actions']['N_kN'] = 99
        model['section']['b_mm'] = 999
        self.assertEqual(parameters, before)
        self.assertEqual(MODEL_SCHEMA, schema_before)
        self.assertIn('actions', MODEL_SCHEMA['properties'])
        self.assertNotIn('analysis_id', MODEL_SCHEMA['properties']['effective_length']['properties'])
        self.assertIsNot(COMMON_MODEL_SCHEMA['properties']['section'], MODEL_SCHEMA['properties']['section'])


if __name__ == '__main__':
    unittest.main()
