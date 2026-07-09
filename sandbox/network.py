import os, sys, json, atexit, socket, logging, threading
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
_firewall_rules_registry = set()
_fw_lock = threading.Lock()

_PRIVATE_CIDRS = [
    ("Loopback",   "127.0.0.0/8"),
    ("Private10",  "10.0.0.0/8"),
    ("Private172", "172.16.0.0/12"),
    ("Private192", "192.168.0.0/16"),
]


def _cleanup_orphaned_firewall_rules():
    with _fw_lock:
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
    def __init__(self, sandbox_root: str, allowed_hosts: Optional[List[str]] = None,
                 appcontainer_sid_str: str = ""):
        self.allowed_hosts = allowed_hosts or []
        self._sid_str = appcontainer_sid_str  # "S-1-15-2-..." or empty
        self._active = False
        self._firewall_rules = []
        self._stats = {"blocked_count": 0, "allowed_count": 0}

    def activate(self):
        if self._active:
            return
        if self.allowed_hosts:
            try:
                self._setup_firewall_rules()
            except Exception as e:
                logger.warning(f"Firewall rule setup failed (non-fatal): {e}")
        self._active = True
        mode = "whitelist" if self.allowed_hosts else "pass-through"
        logger.info(f"Network sandbox activated (mode={mode}, sid={'yes' if self._sid_str else 'no'})")

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

    def _make_identity(self, rule, proc_path: str):
        """Apply the identity condition: AppContainer SID or program name fallback."""
        if self._sid_str:
            rule.LocalUser = self._sid_str  # "S-1-15-2-..."
        else:
            rule.ApplicationName = proc_path

    def _setup_firewall_rules(self):
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            proc_path = sys.executable.lower()
            has_sid = bool(self._sid_str)

            # ── 1. 显式阻断私有地址段 ──
            for label, cidr in _PRIVATE_CIDRS:
                rule = win32com.client.Dispatch("HNetCfg.FWRule")
                rule.Name = f"Sandbox_Block_{label}_{id(self)}"
                rule.Description = f"Sandbox block private: {cidr}"
                rule.Action = 0  # Block
                rule.Direction = 1  # Outbound
                rule.Enabled = True
                rule.Profiles = 0x7FFFFFFF
                rule.RemoteAddresses = cidr
                rule.Protocol = 6  # TCP
                self._make_identity(rule, proc_path)
                try:
                    fw_policy.Rules.Add(rule)
                    nm = rule.Name
                    self._firewall_rules.append(nm)
                    _firewall_rules_registry.add(nm)
                except Exception as e:
                    logger.warning(f"Private block rule failed for {cidr}: {e}")

            # ── 2. 放行代理端口 (127.0.0.1:23100-23199) ──
            allow_proxy = win32com.client.Dispatch("HNetCfg.FWRule")
            proxy_name = f"Sandbox_Allow_Proxy_{id(self)}"
            # Remove stale first
            try:
                fw_policy.Rules.Remove(proxy_name)
            except Exception:
                pass
            allow_proxy.Name = proxy_name
            allow_proxy.Description = "Sandbox allow proxy"
            allow_proxy.Action = 1  # Allow
            allow_proxy.Direction = 1
            allow_proxy.Enabled = True
            allow_proxy.Profiles = 0x7FFFFFFF
            allow_proxy.Protocol = 6  # TCP
            allow_proxy.RemoteAddresses = "127.0.0.0/8"
            allow_proxy.RemotePorts = "23100-23199"
            self._make_identity(allow_proxy, proc_path)
            try:
                fw_policy.Rules.Add(allow_proxy)
                self._firewall_rules.append(proxy_name)
                _firewall_rules_registry.add(proxy_name)
                logger.info(f"Proxy allow rule added (127.0.0.1:23100-23199)")
            except Exception as e:
                logger.warning(f"Proxy allow rule failed: {e}")

            # ── 3. 阻断所有出站（白名单底网）──
            block_name = f"Sandbox_Block_All_{id(self)}"
            try:
                fw_policy.Rules.Remove(block_name)
            except Exception:
                pass
            block_rule = win32com.client.Dispatch("HNetCfg.FWRule")
            block_rule.Name = block_name
            block_rule.Description = "Sandbox block all outbound"
            block_rule.Action = 0
            block_rule.Direction = 1
            block_rule.Enabled = True
            block_rule.Profiles = 0x7FFFFFFF
            self._make_identity(block_rule, proc_path)
            try:
                fw_policy.Rules.Add(block_rule)
                self._firewall_rules.append(block_name)
                _firewall_rules_registry.add(block_name)
                logger.info(f"Block-all rule added (sid={has_sid})")
            except Exception as e:
                logger.warning(f"Block-all rule failed (not admin?): {e}")

            # ── 4. [仅 fallback] 旧版按域名白名单放行 ──
            if not has_sid:
                for host in self.allowed_hosts:
                    allow_name = f"Sandbox_Allow_{host}_{id(self)}"
                    try:
                        fw_policy.Rules.Remove(allow_name)
                    except Exception:
                        pass
                    ar = win32com.client.Dispatch("HNetCfg.FWRule")
                    ar.Name = allow_name
                    ar.Description = f"Sandbox allow {host}"
                    ar.Action = 1
                    ar.Direction = 1
                    ar.Enabled = True
                    ar.Profiles = 0x7FFFFFFF
                    self._make_identity(ar, proc_path)
                    try:
                        hostname = urlparse(host).hostname if "://" in host else host
                        resolved = socket.gethostbyname(hostname)
                        ar.RemoteAddresses = resolved
                        fw_policy.Rules.Add(ar)
                        self._firewall_rules.append(allow_name)
                        _firewall_rules_registry.add(allow_name)
                        logger.info(f"Allow rule (fallback): {host} -> {resolved}")
                    except Exception as e:
                        logger.warning(f"Allow rule failed for {host}: {e}")
        except ImportError:
            logger.warning("pywin32 not installed, no firewall rules")

    def _cleanup_firewall_rules(self):
        try:
            import win32com.client
            fw_policy = win32com.client.Dispatch("HNetCfg.FwPolicy2")
            with _fw_lock:
                for name in list(self._firewall_rules):
                    try:
                        fw_policy.Rules.Remove(name)
                        _firewall_rules_registry.discard(name)
                    except Exception:
                        pass
                self._firewall_rules.clear()
        except Exception:
            pass
