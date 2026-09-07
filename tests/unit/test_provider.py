import unittest

from floorterminal.services.provider import ProviderInfo


class IntegrationCapabilityTests(unittest.TestCase):
    def test_capabilities_are_independent(self):
        info = ProviderInfo(
            "external",
            "Configured integration",
            supports_asset_status=False,
            supports_messaging=False,
            supports_team_directory=False,
            supports_response_records=True,
            supports_response_record_status=True,
        )
        self.assertTrue(info.supports_response_records)
        self.assertTrue(info.supports_response_record_status)
        self.assertFalse(info.supports_asset_status)
        self.assertFalse(info.supports_messaging)
        self.assertFalse(info.supports_team_directory)


if __name__ == "__main__":
    unittest.main()
