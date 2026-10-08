"""No API/DSH calls: mode, compact handoff and nonduplicated usage evidence."""
import unittest

from devtools.dsh.efficiency import UsageEvidence, reasoning_effort, task_prompt


class EfficiencyTests(unittest.TestCase):
    def test_routine_default_off_and_explicit_modes(self):
        self.assertEqual(reasoning_effort({}), 'off')
        for mode in ('off', 'low', 'high', 'max'):
            self.assertEqual(reasoning_effort({'reasoning_effort': mode}), mode)
        for bad in ('none', '', True, None):
            with self.assertRaises(ValueError): reasoning_effort({'reasoning_effort': bad})

    def test_prompt_has_concrete_scope_and_no_recursive_delegation(self):
        request = {'task': 'Implement frozen schema; run compileall.', 'allowed_paths': ['tools/example.py']}
        prompt = task_prompt(request)
        self.assertIn('tools/example.py', prompt)
        self.assertIn('do not delegate it again', prompt)
        self.assertIn('AGENTS.md once', prompt)
        self.assertIn('<=12 lines', prompt)
        self.assertLess(len(prompt) - len(request['task']), 1300)

    def test_usage_counts_unique_final_messages_only(self):
        meter = UsageEvidence()
        payload = {'event': {'type': 'assistant/message', 'seq': 3, 'data': {'usage': {
            'inputTokens': 100, 'outputTokens': 40, 'cacheReadTokens': 10, 'totalTokens': 150},
            'stream': [{'type': 'usage', 'usage': {'totalTokens': 150}}]}}}
        meter.observe('session.event', payload)
        meter.observe('session.event', payload)
        meter.observe('session.status', payload)
        meter.observe('session.event', {'event': {'type': 'tool/result', 'seq': 4, 'data': {'usage': {'totalTokens': 900}}}})
        meter.observe('session.event', {'event': {'type': 'assistant/message', 'seq': 5, 'data': {'usage': {
            'inputTokens': 30, 'outputTokens': 20, 'totalTokens': 50}}}})
        result = meter.summary()
        self.assertEqual(result['assistant_requests'], 2)
        self.assertEqual(result['usage']['totalTokens'], 200)
        self.assertEqual(result['usage']['inputTokens'], 130)
        result['usage']['totalTokens'] = 999
        self.assertEqual(meter.summary()['usage']['totalTokens'], 200)

    def test_unknown_usage_is_not_zero_cost(self):
        meter = UsageEvidence()
        meter.observe('session.event', {'event': {'type': 'assistant/message', 'seq': 1, 'data': {}}})
        self.assertIsNone(meter.summary()['usage'])


if __name__ == '__main__': unittest.main()
