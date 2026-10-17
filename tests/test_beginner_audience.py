import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from studio import config, make, writer, pipeline


class BeginnerAudienceTests(unittest.TestCase):
    def test_default_and_case_normalization(self):
        self.assertEqual(config.DEFAULTS['audience'], 'common')
        self.assertEqual(writer.audience_key({'audience': 'Beginner'}), 'beginner')
        self.assertEqual(writer.audience_key({'audience': 'unknown'}), 'common')

    def test_make_rules_override_model_and_explicit_choice_overrides_rules(self):
        with patch.object(make, '_llm', return_value=({'audience': 'expert'}, 'test')):
            self.assertEqual(make.parse('Make a beginner-friendly Short', {})['spec']['pipeline']['audience'], 'beginner')
            self.assertEqual(make.parse('Make a beginner-friendly Short', {}, audience='common')['spec']['pipeline']['audience'], 'common')
        with patch.object(make, '_llm', return_value=(None, 'off')):
            self.assertEqual(make.parse('Make a Short', {})['spec']['pipeline']['audience'], '')
            with self.assertRaises(ValueError): make.parse('Make a Short', {}, audience='invalid')

    def test_job_creation_retains_beginner_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(config, 'load', return_value={**config.DEFAULTS, 'jobs_dir': temp}), patch('threading.Thread.start'):
            studio = pipeline.Studio()
            jid = studio.create('', 1, transcript_text='A source passage.', audience='beginner', mode='short')
            self.assertEqual(studio.job(jid).state['audience'], 'beginner')

    def test_jargon_review_preserves_deeper_beginner_explanations(self):
        class FakeLLM:
            def trace(self, _): return self
            def chat_json(self, system, prompt, **kwargs):
                self.prompt = prompt
                return {'terms': [{'term': 'GFS', 'section': 's0'}], 'sections': [{'id': 's0', 'vo': 'GFS is a weather model that uses measurements to predict future weather.'}]}
        llm = FakeLLM()
        plan = {'sections': [{'id': 's0', 'vo': 'GFS predicts weather.'}]}
        writer.jargon_check(llm, plan, {'audience': 'beginner'}, lambda _: None)
        self.assertIn('weather model', plan['sections'][0]['vo'])
        self.assertIn('Spelling out an acronym alone is not an explanation', llm.prompt)
        self.assertIn('preserve', writer.FACT_AUDIENCE['beginner'])

    def test_beginner_jargon_rewrite_cannot_remove_acronyms(self):
        class FakeLLM:
            def trace(self, _): return self
            def chat_json(self, *args, **kwargs):
                return {'sections': [{'id': 's0', 'vo': 'A program predicts weather for you.'}, {'id': 'unknown', 'vo': 'Ignore this.'}]}
        plan = {'sections': [{'id': 's0', 'vo': 'GFS predicts weather.'}]}
        writer.jargon_check(FakeLLM(), plan, {'audience': 'beginner'}, lambda _: None)
        self.assertEqual(plan['sections'][0]['vo'], 'GFS predicts weather.')


if __name__ == '__main__': unittest.main()
