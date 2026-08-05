import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "agents"))

try:
    import kubernetes  # noqa: F401
except ModuleNotFoundError:
    kubernetes_module = types.ModuleType("kubernetes")
    client_module = types.ModuleType("kubernetes.client")
    config_module = types.ModuleType("kubernetes.config")

    class ConfigException(Exception):
        pass

    config_module.ConfigException = ConfigException
    config_module.load_incluster_config = Mock(side_effect=ConfigException)
    config_module.load_kube_config = Mock()
    client_module.CoreV1Api = Mock
    kubernetes_module.client = client_module
    kubernetes_module.config = config_module
    sys.modules["kubernetes"] = kubernetes_module
    sys.modules["kubernetes.client"] = client_module
    sys.modules["kubernetes.config"] = config_module

import tools


def make_pod(labels=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            labels=labels or {}
        )
    )


class RestartPodToolTest(unittest.TestCase):
    def setUp(self):
        tools._action_history.clear()

    def test_restart_pod_deletes_only_the_affected_pod(self):
        core_v1 = Mock()
        core_v1.read_namespaced_pod.return_value = make_pod()

        with patch.object(tools, "_get_core_v1", return_value=core_v1):
            result = tools.restart_pod.invoke({"pod_name": "mock-model-abc123"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["restarted_pod"], "mock-model-abc123")
        core_v1.read_namespaced_pod.assert_called_once_with(
            name="mock-model-abc123",
            namespace=tools.NAMESPACE,
        )
        core_v1.delete_namespaced_pod.assert_called_once_with(
            name="mock-model-abc123",
            namespace=tools.NAMESPACE,
        )
        core_v1.list_namespaced_pod.assert_not_called()
        self.assertEqual(len(tools._action_history), 1)

    def test_restart_pod_skips_excluded_pod(self):
        core_v1 = Mock()
        core_v1.read_namespaced_pod.return_value = make_pod({"critical": "true"})

        with patch.object(tools, "_get_core_v1", return_value=core_v1):
            result = tools.restart_pod.invoke({"pod_name": "critical-pod"})

        self.assertEqual(result["status"], "skipped")
        self.assertIn("excluded", result["reason"])
        core_v1.delete_namespaced_pod.assert_not_called()
        self.assertEqual(len(tools._action_history), 0)

    def test_restart_pod_does_not_delete_during_cooldown(self):
        core_v1 = Mock()
        core_v1.read_namespaced_pod.return_value = make_pod()
        tools._action_history.append(datetime.now(timezone.utc))

        with patch.object(tools, "_get_core_v1", return_value=core_v1):
            result = tools.restart_pod.invoke({"pod_name": "mock-model-abc123"})

        self.assertEqual(result["status"], "cooldown")
        core_v1.delete_namespaced_pod.assert_not_called()

    def test_restart_pod_does_not_delete_when_circuit_breaker_tripped(self):
        core_v1 = Mock()
        core_v1.read_namespaced_pod.return_value = make_pod()
        recent_action = datetime.now(timezone.utc) - timedelta(minutes=5)
        tools._action_history.extend([recent_action] * tools.MAX_ACTIONS_PER_HOUR)

        with patch.object(tools, "_get_core_v1", return_value=core_v1):
            result = tools.restart_pod.invoke({"pod_name": "mock-model-abc123"})

        self.assertEqual(result["status"], "circuit_breaker_tripped")
        core_v1.delete_namespaced_pod.assert_not_called()

    def test_restart_pod_skips_when_no_pod_name_is_provided(self):
        with patch.object(tools, "_get_core_v1") as get_core_v1:
            result = tools.restart_pod.invoke({"pod_name": ""})

        self.assertEqual(result["status"], "skipped")
        get_core_v1.assert_not_called()


if __name__ == "__main__":
    unittest.main()
