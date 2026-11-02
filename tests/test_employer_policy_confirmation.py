import unittest

from employer_guard import contact_reason


class EmployerPolicyConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.vacancy = {"employer": {"id": "123", "name": "Acme Analytics"}, "name": "Analyst"}

    def test_empty_exclusion_list_requires_explicit_confirmation(self):
        profile = {
            "employer_contact_policy": {"strict": True},
            "excluded_employers": [],
            "employer_exclusions_confirmed": False,
        }
        self.assertIn("Нет подтверждённых", contact_reason(self.vacancy, profile))

    def test_explicitly_confirmed_empty_list_allows_known_employer(self):
        profile = {
            "employer_contact_policy": {"strict": True},
            "excluded_employers": [],
            "employer_exclusions_confirmed": True,
        }
        self.assertIsNone(contact_reason(self.vacancy, profile))

    def test_valid_exclusion_list_blocks_match_without_new_confirmation_flag(self):
        profile = {
            "employer_contact_policy": {"strict": True},
            "excluded_employers": [{"company": "Acme Analytics", "aliases": ["Acme"], "hh_ids": ["123"]}],
        }
        self.assertIsNotNone(contact_reason(self.vacancy, profile))

    def test_invalid_nonempty_list_stays_blocked(self):
        for exclusions in ([{}], [{"company": "Acme", "aliases": [], "hh_ids": []}], None):
            with self.subTest(exclusions=exclusions):
                profile = {
                    "employer_contact_policy": {"strict": True},
                    "excluded_employers": exclusions,
                    "employer_exclusions_confirmed": True,
                }
                self.assertIsNotNone(contact_reason(self.vacancy, profile))

    def test_unconfirmed_legacy_empty_list_remains_blocked(self):
        profile = {"employer_contact_policy": {"strict": True}, "excluded_employers": []}
        self.assertIsNotNone(contact_reason(self.vacancy, profile))


if __name__ == "__main__":
    unittest.main()
