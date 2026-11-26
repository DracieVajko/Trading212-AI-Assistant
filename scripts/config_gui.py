"""Graphical configuration editor for Portfolio AI Assistant.

Edits two files:
  * ~/.portfolio-secrets/api.env  (secrets + provider keys)  -- external, gitignored
  * portfolio_config.json         (execution toggles, caps, behaviour)

Run:  py -3.12 scripts/config_gui.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = Path(os.getenv("PORTFOLIO_SECRETS_FILE", str(Path.home() / ".portfolio-secrets" / "api.env"))).expanduser()
CONFIG_PATH = ROOT / "portfolio_config.json"


def _load_secrets() -> dict[str, str]:
    vals: dict[str, str] = {}
    if SECRETS_PATH.is_file():
        for raw in SECRETS_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    return vals


def _save_secrets(vals: dict[str, str]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for k in sorted(vals):
        if vals[k] != "":
            lines.append(f"{k}={vals[k]}")
    SECRETS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# ---- secret keys we edit ----
SECRET_KEYS = [
    ("TRADING212_API_KEY", "Trading212 LIVE API key"),
    ("TRADING212_API_SECRET", "Trading212 LIVE API secret"),
    ("T212_DEMO_API_KEY", "Trading212 DEMO API key"),
    ("T212_DEMO_API_SECRET", "Trading212 DEMO API secret"),
    ("T212_LIVE_ORDER_ENABLED", "Live orders enabled (0/1)"),
    ("T212_LIVE_ACK", "Live ack (I_UNDERSTAND_LIVE_TRADING)"),
    ("T212_LIVE_BUY_AUTO_APPROVE", "Live auto-approve buys+sells (0/1)"),
    ("T212_DEMO_ORDER_ENABLED", "Demo orders enabled (0/1)"),
    ("T212_ORDER_ENV", "Order env (demo/live)"),
    ("GEMINI_API_KEY", "Gemini API key"),
    ("OPENROUTER_API_KEY", "OpenRouter API key"),
    ("MISTRAL_API_KEY", "Mistral API key"),
    ("OPENCODE_ZEN_API_KEY", "OpenCode Zen API key"),
    ("LM_STUDIO_BASE_URL", "LM Studio base URL"),
    ("LM_STUDIO_MODEL", "LM Studio model"),
    ("OLLAMA_ENABLED", "Ollama enabled (0/1)"),
    ("LM_STUDIO_TASK_PRIORITY", "Watchdog priority (1=priority,0=coop)"),
    ("NOTIFY_EMAIL", "Notify email (sender)"),
    ("NOTIFY_EMAIL_PASSWORD", "Notify email password (app password)"),
    ("NOTIFY_EMAIL_TO", "Notify email recipient"),
    ("NOTIFY_NTFY_TOPIC", "ntfy.sh topic"),
]


class ConfigGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Portfolio AI Assistant - Configuration")
        self.geometry("720x640")
        self.secrets = _load_secrets()
        self.config = _load_config()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- Secrets tab ----
        sec_frame = ttk.Frame(nb)
        nb.add(sec_frame, text="Secrets / API keys")
        self.secret_vars: dict[str, tk.StringVar] = {}
        canvas = tk.Canvas(sec_frame)
        scroll = ttk.Scrollbar(sec_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for key, label in SECRET_KEYS:
            row = ttk.Frame(inner)
            row.pack(fill="x", pady=2, padx=4)
            ttk.Label(row, text=label, width=34).pack(side="left")
            var = tk.StringVar(value=self.secrets.get(key, ""))
            self.secret_vars[key] = var
            show = "*" if "KEY" in key or "SECRET" in key or "PASSWORD" in key else ""
            ttk.Entry(row, textvariable=var, width=40, show=show).pack(side="left", fill="x", expand=True)

        # ---- Execution tab ----
        exec_frame = ttk.Frame(nb)
        nb.add(exec_frame, text="Execution")
        exec_cfg = (self.config.get("day_trader") or {}).get("execution", {}) or {}
        self.exec_vars: dict[str, Any] = {}
        exec_fields = [
            ("enabled", "Execution enabled", "bool"),
            ("environment", "Environment (demo/live)", "str"),
            ("auto_approve", "Auto-approve (demo only)", "bool"),
            ("live_buy_auto_approve", "Live auto-approve buys+sells", "bool"),
            ("allowed_sides", "Allowed sides (BUY,SELL)", "list"),
            ("max_order_eur", "Max order EUR", "float"),
            ("max_sell_eur", "Max sell EUR (conservative cap)", "float"),
            ("max_daily_orders", "Max daily orders", "int"),
            ("max_daily_loss", "Max daily loss EUR", "float"),
            ("demo_enabled", "Demo enabled", "bool"),
            ("live_enabled", "Live enabled", "bool"),
            ("demo_allowed_sides", "Demo allowed sides", "list"),
            ("live_allowed_sides", "Live allowed sides", "list"),
            ("demo_max_order_eur", "Demo max order EUR (0=global)", "float"),
            ("demo_max_sell_eur", "Demo max sell EUR (0=global)", "float"),
            ("live_max_order_eur", "Live max order EUR (0=global)", "float"),
            ("live_max_sell_eur", "Live max sell EUR (0=global)", "float"),
            ("live_ack", "Live ack string", "str"),
        ]
        for key, label, typ in exec_fields:
            row = ttk.Frame(exec_frame)
            row.pack(fill="x", pady=2, padx=4)
            ttk.Label(row, text=label, width=34).pack(side="left")
            val = exec_cfg.get(key, "")
            if typ == "bool":
                var = tk.BooleanVar(value=bool(val))
            elif typ == "list":
                var = tk.StringVar(value=", ".join(val) if isinstance(val, list) else str(val))
            else:
                var = tk.StringVar(value=str(val) if val != "" else "")
            self.exec_vars[key] = (var, typ)
            if typ == "bool":
                ttk.Checkbutton(row, variable=var).pack(side="left")
            else:
                ttk.Entry(row, textvariable=var, width=30).pack(side="left", fill="x", expand=True)

        # ---- AI / Provider tab ----
        ai_frame = ttk.Frame(nb)
        nb.add(ai_frame, text="AI / Providers")
        settings = self.config.get("settings", {}) or {}
        self.ai_vars: dict[str, tk.StringVar] = {}
        ai_fields = [
            ("provider", "Provider (auto/lmstudio/ollama/gemini/...)"),
            ("execution_mode", "Execution mode (auto/public/locals)"),
            ("lm_studio_base_url", "LM Studio base URL"),
            ("lm_studio_model", "LM Studio model"),
            ("lm_studio_context_tokens", "LM Studio context tokens"),
            ("lm_studio_max_output_tokens", "LM Studio max output tokens"),
            ("lm_studio_reasoning_effort", "LM Studio reasoning effort"),
            ("ollama_base_url", "Ollama base URL"),
            ("ollama_model", "Ollama model"),
            ("max_concurrent_models", "Max concurrent models"),
            ("lm_studio_task_priority", "Watchdog priority (1/0)"),
            ("lm_studio_watchdog_timeout_s", "Watchdog timeout (s)"),
            ("lm_studio_watchdog_poll_s", "Watchdog poll (s)"),
        ]
        for key, label in ai_fields:
            row = ttk.Frame(ai_frame)
            row.pack(fill="x", pady=2, padx=4)
            ttk.Label(row, text=label, width=34).pack(side="left")
            val = settings.get(key, "")
            var = tk.StringVar(value=str(val) if val != "" else "")
            self.ai_vars[key] = var
            ttk.Entry(row, textvariable=var, width=40).pack(side="left", fill="x", expand=True)

        # ---- Save button ----
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=8)
        ttk.Button(btn_frame, text="Save", command=self.save).pack(side="right")
        ttk.Button(btn_frame, text="Reload", command=self.reload).pack(side="right", padx=4)
        self.status = ttk.Label(btn_frame, text=f"Secrets: {SECRETS_PATH}")
        self.status.pack(side="left")

    def reload(self):
        self.secrets = _load_secrets()
        self.config = _load_config()
        for key, var in self.secret_vars.items():
            var.set(self.secrets.get(key, ""))
        exec_cfg = (self.config.get("day_trader") or {}).get("execution", {}) or {}
        for key, (var, typ) in self.exec_vars.items():
            val = exec_cfg.get(key, "")
            if typ == "bool":
                var.set(bool(val))
            elif typ == "list":
                var.set(", ".join(val) if isinstance(val, list) else str(val))
            else:
                var.set(str(val) if val != "" else "")
        settings = self.config.get("settings", {}) or {}
        for key, var in self.ai_vars.items():
            var.set(str(settings.get(key, "")))
        self.status.config(text="Reloaded.")

    def save(self):
        # Secrets
        for key, var in self.secret_vars.items():
            self.secrets[key] = var.get().strip()
        # Remove empty
        self.secrets = {k: v for k, v in self.secrets.items() if v != ""}
        _save_secrets(self.secrets)

        # Config
        cfg = self.config
        if "day_trader" not in cfg or not isinstance(cfg.get("day_trader"), dict):
            cfg["day_trader"] = {}
        if "execution" not in cfg["day_trader"] or not isinstance(cfg["day_trader"].get("execution"), dict):
            cfg["day_trader"]["execution"] = {}
        exec_cfg = cfg["day_trader"]["execution"]
        for key, (var, typ) in self.exec_vars.items():
            if typ == "bool":
                exec_cfg[key] = bool(var.get())
            elif typ == "list":
                exec_cfg[key] = [x.strip() for x in str(var.get()).split(",") if x.strip()]
            elif typ == "int":
                try:
                    exec_cfg[key] = int(var.get())
                except ValueError:
                    exec_cfg[key] = 0
            elif typ == "float":
                try:
                    exec_cfg[key] = float(var.get())
                except ValueError:
                    exec_cfg[key] = 0.0
            else:
                exec_cfg[key] = var.get().strip()
        if "settings" not in cfg or not isinstance(cfg.get("settings"), dict):
            cfg["settings"] = {}
        settings = cfg["settings"]
        for key, var in self.ai_vars.items():
            val = var.get().strip()
            # type coercion for numeric
            if key in ("lm_studio_context_tokens", "lm_studio_max_output_tokens", "max_concurrent_models",
                       "lm_studio_watchdog_timeout_s", "lm_studio_watchdog_poll_s"):
                try:
                    settings[key] = int(val)
                except ValueError:
                    settings[key] = 0
            else:
                settings[key] = val
        _save_config(cfg)
        self.status.config(text=f"Saved. Secrets: {SECRETS_PATH}")


if __name__ == "__main__":
    app = ConfigGUI()
    app.mainloop()