import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LinuxPackagingTests(unittest.TestCase):
    def test_pi_release_wrapper_expects_the_complete_sorted_release(self):
        wrapper = (ROOT / "scripts/install/prepare_release_on_pi.sh").read_text()
        expected = (
            "expected=$'DEPLOYMENT.txt\\nLICENSE\\nSBOM.spdx.json\\nSHA256SUMS\\n"
            "SOFTWARE_INFORMATION_AND_NOTICES.txt\\nVERSION\\nconfig.json\\n"
            "connector.json\\nfloorterminal\\nfloorterminal-icon.png\\n"
            "floorterminal-launch\\nfloorterminal.desktop\\n"
            "floorterminal.service\\ninstall.sh'"
        )
        self.assertIn(expected, wrapper)
        self.assertIn("xauth xvfb", wrapper)
        self.assertIn(
            'xvfb-run -a -s "-screen 0 1920x1200x24 -dpi 96 -nolisten tcp" python3 "$BUILD_SCRIPT"',
            wrapper,
        )

    def test_installer_activates_supervised_user_service(self):
        installer = (ROOT / "packaging/linux/install.sh").read_text()
        desktop = (ROOT / "packaging/linux/floorterminal.desktop").read_text()
        service = (ROOT / "packaging/linux/floorterminal.service").read_text()
        self.assertIn("floorterminal.service", installer)
        self.assertIn("systemctl --user", installer)
        self.assertIn("systemctl --user restart floorterminal.service", desktop)
        self.assertIn("Icon=/opt/floorterminal/floorterminal-icon.png", desktop)
        self.assertIn('"$SOURCE_DIR/floorterminal-icon.png"', installer)
        self.assertIn("Restart=always", service)
        # The service starts the supervised launcher, which performs the update
        # boot watchdog check before handing over to the active version link.
        self.assertIn("ExecStart=/opt/floorterminal/bin/floorterminal-launch", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("PrivateDevices=false", service)
        for control in (
            "ProtectSystem=strict",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "RestrictNamespaces=true",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            "CapabilityBoundingSet=",
            "UMask=0077",
        ):
            self.assertIn(control, service)


if __name__ == "__main__":
    unittest.main()
