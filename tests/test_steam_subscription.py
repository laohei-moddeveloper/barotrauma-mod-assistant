import ctypes
import io
import json
import threading
import unittest
from unittest.mock import patch
from mod_assistant.core import AssistantError, Cancelled
from mod_assistant.steam import SteamBridge, SUBSCRIBED
from mod_assistant.friends import verify_workshop_items


class SubscriptionTests(unittest.TestCase):
    def bridge(self,states,completed=True,failed=False):
        bridge=SteamBridge(None); bridge.ugc=1; bridge.utils=1
        state=iter(states); bridge.state=lambda item:next(state)
        bridge.subscribe_item=lambda *args:42; bridge.pump=lambda:{}
        def finish(utils,call,pointer):
            ctypes.cast(pointer,ctypes.POINTER(ctypes.c_bool))[0]=failed
            return completed
        bridge.call_completed=finish
        return bridge

    def test_success_requires_confirmed_subscription_state(self):
        self.assertTrue(self.bridge([0,SUBSCRIBED]).subscribe('101',process_guard=lambda:False))
        self.assertFalse(self.bridge([SUBSCRIBED]).subscribe('101',process_guard=lambda:False))
        with self.assertRaisesRegex(AssistantError,'未确认订阅'):
            self.bridge([0,0]).subscribe('101',process_guard=lambda:False)

    def test_failure_timeout_cancel_and_running_game(self):
        with self.assertRaisesRegex(AssistantError,'请求失败'):
            self.bridge([0],failed=True).subscribe('101',process_guard=lambda:False)
        with self.assertRaisesRegex(AssistantError,'超时'):
            self.bridge([0]).subscribe('101',timeout=0,process_guard=lambda:False)
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): self.bridge([0]).subscribe('101',cancel=cancel,process_guard=lambda:False)
        with self.assertRaises(AssistantError): self.bridge([]).subscribe('101',process_guard=lambda:True)

    def test_invalid_ids_never_reach_native_call(self):
        for item in ('0','-1','../101',str(2**64)):
            with self.assertRaises(AssistantError): self.bridge([]).subscribe(item,process_guard=lambda:False)

    def test_imported_ids_must_belong_to_barotrauma_before_subscription(self):
        for appid in (602960,123):
            response={'response':{'publishedfiledetails':[{'publishedfileid':'101','result':1,'consumer_app_id':appid}]}}
            with patch('mod_assistant.friends.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
                if appid==602960: verify_workshop_items(['101'])
                else:
                    with self.assertRaisesRegex(AssistantError,'未订阅'): verify_workshop_items(['101'])
        with patch('mod_assistant.friends.urllib.request.urlopen',side_effect=OSError('network unavailable')):
            with self.assertRaisesRegex(AssistantError,'未订阅'): verify_workshop_items(['101'])
