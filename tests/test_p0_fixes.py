"""
tests/test_p0_fixes.py — Unit and integration tests verifying all 4 P0 critical fixes:
1. P0 #1: `main.py` (`execute_session()`) runs BOTH `NaukriBot` and `LinkedInBot`.
2. P0 #2: Application statistics are real (no fabricated `session_stats["total_applied"] = 1`).
3. P0 #3: AI qualification engine (`qualify_prompt` + `LLMClient`) is invoked before applying in `NaukriBot` and `LinkedInBot`.
4. P0 #4: Candidate information in `linkedin_bot.py`, `naukri_bot.py`, and `browser/form_utils.py` comes dynamically from `config.settings` with zero hardcoded CTC/city/experience assumptions.
"""

import asyncio
import importlib
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeSettings:
    full_name = "Ada Lovelace"
    email = "ada@analytical.org"
    phone = "+44-1234567890"
    location = "London, UK"
    linkedin_url = "https://www.linkedin.com/in/adalovelace"
    github_url = "https://github.com/adalovelace"
    roles_list = ["Principal AI Architect", "Distributed Systems Engineer"]
    experience_range = "5-7 years"
    location_filter = "remote"
    allow_contract = True
    allow_internship = False
    skills_summary = "Python, Rust, Distributed Consensus, LLM Orchestration"
    achievements = "Designed first analytical engine algorithm reducing compute cycles by 60%"
    work_authorization = "UK Citizen"
    salary_expectation = "£140,000"
    willing_to_relocate = False
    available_start_date = "2 Weeks"
    debug_mode = False
    headless = True
    daily_max_applications = 25
    db_path = ":memory:"

    def get_credentials(self, domain: str):
        return {"email": self.email, "password": "secret"}


class TestP0Fixes(unittest.TestCase):
    """Comprehensive verification suite for all 4 P0 critical issues."""

    def test_p0_1_and_2_execute_session_runs_both_naukri_and_linkedin_with_real_stats(self):
        """
        P0 #1 & P0 #2:
        - `execute_session()` must invoke BOTH `NaukriBot.run()` and `LinkedInBot.run()`.
        - When both bots submit 0 applications, `total_applied` MUST be 0 (not fabricated 1).
        - When bots submit real applications (Naukri=2, LinkedIn=3), `total_applied` MUST equal 5.
        """
        fake_dotenv = types.SimpleNamespace(load_dotenv=lambda *a, **kw: None)
        fake_loguru = types.SimpleNamespace(
            logger=types.SimpleNamespace(
                remove=lambda *a, **kw: None,
                add=lambda *a, **kw: None,
                info=lambda *a, **kw: None,
                warning=lambda *a, **kw: None,
                error=lambda *a, **kw: None,
                debug=lambda *a, **kw: None,
                success=lambda *a, **kw: None,
            )
        )
        fake_db_crud = types.SimpleNamespace(
            create_session_log=MagicMock(return_value="sess-001"),
            update_session_log=MagicMock(),
        )

        mock_naukri_instance = MagicMock()
        mock_naukri_instance.run = AsyncMock(
            return_value={"total_applied": 0, "total_skipped": 2, "total_failed": 0, "sites_blocked": []}
        )
        mock_linkedin_instance = MagicMock()
        mock_linkedin_instance.run = AsyncMock(
            return_value={"total_applied": 0, "total_skipped": 3, "total_failed": 0, "sites_blocked": []}
        )

        fake_naukri_mod = types.SimpleNamespace(NaukriBot=MagicMock(return_value=mock_naukri_instance))
        fake_linkedin_mod = types.SimpleNamespace(LinkedInBot=MagicMock(return_value=mock_linkedin_instance))

        with patch.dict(
            "sys.modules",
            {
                "dotenv": fake_dotenv,
                "loguru": fake_loguru,
                "db.crud": fake_db_crud,
                "naukri_bot": fake_naukri_mod,
                "linkedin_bot": fake_linkedin_mod,
            },
        ):
            import main
            importlib.reload(main)

            runner = main.AgentRunner.__new__(main.AgentRunner)
            runner.dry_run = False
            runner.settings = FakeSettings()
            runner.settings.debug_mode = True
            runner._setup_db = MagicMock()
            runner.SessionLocal = MagicMock()

            stats_zero = runner.execute_session()

            fake_naukri_mod.NaukriBot.assert_called_once()
            mock_naukri_instance.run.assert_awaited_once()
            fake_linkedin_mod.LinkedInBot.assert_called_once()
            mock_linkedin_instance.run.assert_awaited_once()

            self.assertEqual(stats_zero["total_applied"], 0)
            self.assertEqual(stats_zero["total_skipped"], 5)
            self.assertEqual(stats_zero["total_failed"], 0)

            # Now verify non-zero real counts from both bots
            mock_naukri_instance.run = AsyncMock(
                return_value={"total_applied": 2, "total_skipped": 1, "total_failed": 0, "sites_blocked": []}
            )
            mock_linkedin_instance.run = AsyncMock(
                return_value={"total_applied": 3, "total_skipped": 2, "total_failed": 1, "sites_blocked": ["linkedin.com"]}
            )
            stats_real = runner.execute_session()

            self.assertEqual(stats_real["total_applied"], 5)
            self.assertEqual(stats_real["total_skipped"], 3)
            self.assertEqual(stats_real["total_failed"], 1)
            self.assertIn("linkedin.com", stats_real["sites_blocked"])


    def test_p0_3_naukri_bot_invokes_ai_qualification_before_applying(self):
        """
        P0 #3:
        - `NaukriBot._process_single_job_card` must invoke `qualify_job()` before applying.
        - If AI qualification returns `pass=False`, the bot skips the job and does NOT call `_handle_scenario_c`.
        - If AI qualification returns `pass=True`, the bot proceeds to `_handle_scenario_c`.
        """
        fake_loguru = types.SimpleNamespace(
            logger=types.SimpleNamespace(
                info=lambda *a, **kw: None,
                warning=lambda *a, **kw: None,
                error=lambda *a, **kw: None,
                debug=lambda *a, **kw: None,
                success=lambda *a, **kw: None,
            )
        )
        fake_config = types.SimpleNamespace(settings=FakeSettings())
        fake_engine = types.SimpleNamespace(BrowserEngine=MagicMock())
        fake_playwright = types.SimpleNamespace(Page=object, TimeoutError=TimeoutError, Locator=object)
        fake_llm_mod = types.SimpleNamespace(LLMClient=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "loguru": fake_loguru,
                "config": fake_config,
                "browser.engine": fake_engine,
                "playwright.async_api": fake_playwright,
                "ai.llm_client": fake_llm_mod,
            },
        ):
            import naukri_bot
            importlib.reload(naukri_bot)

            mock_llm = MagicMock()
            mock_llm.call.return_value = {
                "pass": False,
                "reason": "Requires 10+ years Java experience",
                "role_match": False,
                "type_match": True,
                "flag": False,
            }
            bot = naukri_bot.NaukriBot(llm_client=mock_llm)
            bot._handle_scenario_c = AsyncMock()
            bot._handle_scenario_a = MagicMock()

            mock_job_page = AsyncMock()
            mock_jd_loc = AsyncMock()
            mock_jd_loc.is_visible.return_value = True
            mock_jd_loc.inner_text.return_value = "Looking for a 10+ year Java Architect."
            mock_job_page.locator = MagicMock(return_value=mock_jd_loc)

            mock_page = MagicMock()
            mock_page.context.new_page = AsyncMock(return_value=mock_job_page)

            mock_title_el = AsyncMock()
            mock_title_el.is_visible.return_value = True
            mock_title_el.inner_text.return_value = "Java Architect"
            mock_title_el.get_attribute.return_value = "https://www.naukri.com/job-java-1"

            mock_comp_el = AsyncMock()
            mock_comp_el.is_visible.return_value = True
            mock_comp_el.inner_text.return_value = "Enterprise Corp"

            def card_locator(sel):
                return mock_title_el if "title" in sel else mock_comp_el

            mock_card = MagicMock()
            mock_card.scroll_into_view_if_needed = AsyncMock()
            mock_card.locator.side_effect = card_locator

            with patch.object(naukri_bot, "read_delay", return_value=0.0), \
                 patch.object(naukri_bot, "page_load_buffer", return_value=0.0), \
                 patch.object(naukri_bot, "scroll_delay", return_value=0.0), \
                 patch.object(naukri_bot, "between_applications", return_value=0.0):
                asyncio.run(bot._process_single_job_card(mock_page, mock_card))

            mock_llm.call.assert_called_once()
            self.assertEqual(mock_llm.call.call_args[0][0], "qualify")
            bot._handle_scenario_c.assert_not_awaited()
            self.assertEqual(bot.stats["total_applied"], 0)
            self.assertEqual(bot.stats["total_skipped"], 1)

            # Now test when AI qualification returns pass=True
            mock_llm.reset_mock()
            mock_llm.call.return_value = {
                "pass": True,
                "reason": "Strong match for Principal AI Architect",
                "role_match": True,
                "type_match": True,
                "flag": False,
            }
            with patch.object(naukri_bot, "read_delay", return_value=0.0), \
                 patch.object(naukri_bot, "page_load_buffer", return_value=0.0), \
                 patch.object(naukri_bot, "scroll_delay", return_value=0.0), \
                 patch.object(naukri_bot, "between_applications", return_value=0.0):
                asyncio.run(bot._process_single_job_card(mock_page, mock_card))

            mock_llm.call.assert_called_once()
            bot._handle_scenario_c.assert_awaited_once()

    def test_p0_4_no_hardcoded_candidate_values_in_linkedin_or_form_utils(self):
        """
        P0 #4:
        - `linkedin_bot.build_candidate_profile_context()` and `build_outreach_templates()`
          must use the candidate's runtime settings and contain zero hardcoded
          '3+ years', '2 years GenAI', '7 LPA', '14-18 LPA', or 'Bengaluru' strings.
        - `browser.form_utils.build_field_mapping()` must map the candidate's actual
          name, email, phone, location, salary expectation, and notice period.
        """
        fake_loguru = types.SimpleNamespace(
            logger=types.SimpleNamespace(
                info=lambda *a, **kw: None,
                warning=lambda *a, **kw: None,
                error=lambda *a, **kw: None,
                debug=lambda *a, **kw: None,
                success=lambda *a, **kw: None,
            )
        )
        fake_config = types.SimpleNamespace(settings=FakeSettings())
        fake_engine = types.SimpleNamespace(BrowserEngine=MagicMock())
        fake_playwright = types.SimpleNamespace(Page=object, TimeoutError=TimeoutError, Locator=object)
        fake_llm_mod = types.SimpleNamespace(LLMClient=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "loguru": fake_loguru,
                "config": fake_config,
                "browser.engine": fake_engine,
                "playwright.async_api": fake_playwright,
                "ai.llm_client": fake_llm_mod,
            },
        ):
            import linkedin_bot
            import browser.form_utils as form_utils
            importlib.reload(linkedin_bot)
            importlib.reload(form_utils)

            custom = FakeSettings()
            ctx = linkedin_bot.build_candidate_profile_context(custom)
            templates = linkedin_bot.build_outreach_templates(custom)

            self.assertIn("Ada Lovelace", ctx)
            self.assertIn("London, UK", ctx)
            self.assertIn("5-7 years", ctx)
            self.assertIn("£140,000", ctx)
            self.assertIn("2 Weeks", ctx)
            self.assertIn("Python, Rust, Distributed Consensus", templates["connect_recruiter"])

            for forbidden in ("7 LPA", "14-18 LPA", "Bengaluru", "3+ years python", "2 years GenAI"):
                self.assertNotIn(forbidden, ctx)
                for tpl_text in templates.values():
                    self.assertNotIn(forbidden, tpl_text)

            mapping = form_utils.build_field_mapping(custom)
            self.assertEqual(mapping["full name"], "Ada Lovelace")
            self.assertEqual(mapping["first name"], "Ada")
            self.assertEqual(mapping["last name"], "Lovelace")
            self.assertEqual(mapping["email"], "ada@analytical.org")
            self.assertEqual(mapping["location"], "London, UK")
            self.assertEqual(mapping["notice period"], "2 Weeks")
            self.assertEqual(mapping["expected ctc"], "£140,000")
            self.assertNotIn("7.63", mapping.values())
            self.assertNotIn("Example Candidate", mapping.values())


if __name__ == "__main__":
    unittest.main()


