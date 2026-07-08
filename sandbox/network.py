import os, sys, json, atexit, socket, logging, threading
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
_firewall_rules_registry = set()
_mw_lock = threading.Lock()


def _cleanup_orphaned_firewall_rules():
    with _mw_lock:
        rules = list(_firewall_rules_registry)
        if not rules:
            return
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            for name in rules:
                try:
                    fw_policy.Rules.Remove(name)
                except Exception:
                    pass
        except Exception:
            pass


atexit.register(_cleanup_orphaned_firewall_rules)


class BlockedHostError(Exception):
    pass


class NetworkSandbox:
    def __init__(self, sandbox_root: str, allowed_hosts: Optional[List[str]] = None):
        self.allowed_hosts = allowed_hosts or []
        self._active = False
        self._firewall_rules = []
        self._stats = {"blocked_count": 0, "allowed_count": 0}

    def activate(self):
        if self._active:
            return
        if self.allowed_hosts:
            self._setup_firewall_rules()
        self._active = True
        mode = "whitelist" if self.allowed_hosts else "pass-through"
        logger.info(f"Network sandbox activated (mode={mode}, allowed={len(self.allowed_hosts)})")

    def deactivate(self):
        if not self._active:
            return
        self._cleanup_firewall_rules()
        self._active = False
        logger.info("Network sandbox deactivated")

    def add_allowed_host(self, host: str):
        if host not in self.allowed_hosts:
            self.allowed_hosts.append(host)
            logger.info(f"Added allowed host: {host}")

    def remove_allowed_host(self, host: str):
        if host in self.allowed_hosts:
            self.allowed_hosts.remove(host)

    def get_stats(self) -> dict:
        return dict(self._stats)

    def _setup_firewall_rules(self):
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            rules = fw_policy.Rules
            proc_path = sys.executable.lower()

            block_name = f"Sandbox_Block_{id(self)}"
            try:
                existing = fw_policy.Rules.Item(block_name)
                fw_policy.Rules.Remove(block_name)
            except Exception:
                pass
            new_rule = win32com.client.Dispatch("HNetCfg.FWRule")
            new_rule.Name = block_name
            new_rule.Description = "Sandbox block all outbound"
            new_rule.ApplicationName = proc_path
            new_rule.Action = 0
            new_rule.Direction = 1
            new_rule.Enabled = True
            new_rule.Profiles = 0x7FFFFFFF
            try:
                fw_policy.Rules.Add(new_rule)
                self._firewall_rules.append(block_name)
                _firewall_rules_registry.add(block_name)
                logger.info(f"Firewall block rule added for {proc_path}")
            except Exception as e:
                logger.warning(f"Failed to add block rule (not admin?): {e}")

            for host in self.allowed_hosts:
                allow_rule_name = f"Sandbox_Allow_{host}_{id(self)}"
                try:
                    existing = fw_policy.Rules.Item(allow_rule_name)
                    fw_policy.Rules.Remove(allow_rule_name)
                except Exception:
                    pass
                allow_rule = win32com.client.Dispatch("HNetCfg.FWRule")
                allow_rule.Name = allow_rule_name
                allow_rule.Description = f"Sandbox allow {host}"
                allow_rule.ApplicationName = proc_path
                allow_rule.Action = 1
                allow_rule.Direction = 1
                allow_rule.Enabled = True
                allow_rule.Profiles = 0x7FFFFFFF
                try:
                    hostname = urlparse(host).hostname if "://" in host else host
                    resolved = socket.gethostbyname(hostname)
                    allow_rule.RemoteAddresses = resolved
                    fw_policy.Rules.Add(allow_rule)
                    self._firewall_rules.append(allow_rule_name)
                    _firewall_rules_registry.add(allow_rule_name)
                    logger.info(f"Allow rule added: {host} -> {resolved}")
                except Exception as e:
                    logger.warning(f"Failed to add allow rule for {host}: {e}")
        except ImportError:
            logger.warning("pywin32 not installed, no firewall rules")

    def _cleanup_firewall_rules(self):
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            with _mw_lock:
                for name in list(self._firewall_rules):
                    try:
                        fw_policy.Rules.Remove(name)
                        _firewall_rules_registry.discard(name)
                    except Exception:
                        pass
                self._firewall_rules.clear()
        except Exception:
            pass
