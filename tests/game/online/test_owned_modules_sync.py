"""The account sync takes back modules an account does not own (online
finding 29, the second half).

A Free Mode download is booked as owned in the Free save; before the save
guard (test_mode_switch_save.py), switching to Progress Mode could carry
that record into the account's save. The sync with Omninet only ever added
the server's purchases, so such an account kept the modules: the shop showed
them owned and egg selection offered them. The server's purchase rows are
the whole record of what an account owns (a purchase, or the free first
module at price 0), so a module the local record holds and the rows do not
is dropped; a module the shop no longer lists (a withdrawn Beta module) is
left alone, the listing cannot speak for it.
"""
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
for path in (os.path.join(REPO_ROOT, "tests", "support"), os.path.join(REPO_ROOT, "src"),
             os.path.dirname(os.path.abspath(__file__))):
    if path not in sys.path:
        sys.path.insert(0, path)

MODULES = os.path.join(REPO_ROOT, "modules")
PID = "11111111-2222-3333-4444-555555555555"


def has(*names):
    return all(os.path.exists(os.path.join(MODULES, n, "module.json")) for n in names)


@unittest.skipUnless(has("DMC", "PENC"), "modules/ is gitignored")
class OwnedModulesSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        from online_ui import progress_mode
        self.env.reset()
        self.gg = gg = self.env.gg
        progress_mode(self.env, PID)
        # The shop lists DMC and PENC; the account bought PENC only, and
        # once a Beta module the shop no longer lists.
        self.listing = [
            {"id": "guid-dmc", "name": "DMC", "version": "1.0"},
            {"id": "guid-penc", "name": "PENC", "version": "1.0"},
        ]
        self.rows = [
            {"purchase_type": "module", "item_id": "guid-penc"},
            {"purchase_type": "module", "item_id": "guid-beta"},
        ]
        # The save holds DMC as owned too: a Free Mode download carried in.
        gg.purchases.add_module("guid-dmc", "DMC")
        gg.purchases.add_module("guid-penc", "PENC")
        gg.purchases.add_module("guid-beta", "BETA")

    def sync(self, purchases_ok=True):
        from services.omninet_service import omninet_service
        from utils.module_utils import sync_account_data
        with patch.object(omninet_service, "is_logged_in", return_value=True), \
                patch.object(omninet_service, "get_user_info", return_value={"coins": 7}), \
                patch.object(omninet_service, "get_user_purchases",
                             return_value=(True, {"purchases": self.rows}) if purchases_ok
                             else (False, "Server unavailable")), \
                patch.object(omninet_service, "get_shop_modules", return_value=(True, self.listing)), \
                patch.object(omninet_service, "download_module_zip") as download:
            sync_account_data(download_missing=False)
        download.assert_not_called()

    def test_a_module_the_account_does_not_own_is_taken_back(self):
        from utils import navigation_utils
        self.sync()
        purchases = self.gg.purchases
        self.assertFalse(purchases.owns_module("guid-dmc"))
        self.assertFalse(purchases.owns_module_name("DMC"))
        self.assertTrue(purchases.owns_module("guid-penc"))
        self.assertTrue(purchases.owns_module_name("PENC"))
        self.assertTrue(navigation_utils.has_owned_modules())

    def test_an_account_that_owns_nothing_keeps_nothing(self):
        from utils import navigation_utils
        self.rows = []
        self.sync()
        purchases = self.gg.purchases
        self.assertFalse(purchases.owns_module_name("DMC"))
        self.assertFalse(purchases.owns_module_name("PENC"))
        self.assertFalse(navigation_utils.has_owned_modules())

    def test_a_module_the_shop_no_longer_lists_is_left_alone(self):
        self.sync()
        self.assertTrue(self.gg.purchases.owns_module("guid-beta"))
        self.assertTrue(self.gg.purchases.owns_module_name("BETA"))

    def test_nothing_is_taken_back_when_the_server_cannot_say(self):
        self.sync(purchases_ok=False)
        self.assertTrue(self.gg.purchases.owns_module("guid-dmc"))
        self.assertTrue(self.gg.purchases.owns_module_name("DMC"))


if __name__ == "__main__":
    unittest.main()
