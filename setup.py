"""DeepSeek 工蜂 + Cloudflare 生圖：一鍵安裝到這台 Windows 電腦。

用法（在這個資料夾執行）：
    python setup.py            安裝全部並自我檢查
    python setup.py --check    只做檢查，不改任何東西

會做的事：
  1. pip 安裝需要的套件
  2. 把伺服器程式複製到 C:\\mcp_tools（已有同名檔會先備份）
  3. 把 secrets.env 裡的金鑰寫進使用者環境變數（setx）
  4. 安裝 skill 到 ~/.claude/skills/deepseek-orchestrator（舊的會備份）
  5. 把兩個 MCP server 加進 Claude 桌面 App 設定（先備份設定檔），有 claude CLI 的話也加進 CLI
  6. 檢查：套件、Node、金鑰能不能連到 DeepSeek
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parent
TARGET = Path(r"C:\mcp_tools")
SKILL_DST = Path.home() / ".claude" / "skills" / "deepseek-orchestrator"
DESKTOP_CFG = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
PACKAGES = ["mcp>=1.30", "openai>=1.40", "httpx", "pillow"]
STAMP = time.strftime("%Y%m%d-%H%M%S")


def load_secrets() -> dict:
    secrets = {}
    path = KIT / "secrets.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    secrets[k.strip()] = v.strip()
    return secrets


def step(msg: str) -> None:
    print(f"\n== {msg}")


def pip_install() -> None:
    step("安裝 Python 套件")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", *PACKAGES], check=True)


def copy_files() -> None:
    step(f"複製伺服器程式到 {TARGET}")
    TARGET.mkdir(parents=True, exist_ok=True)
    for src in (KIT / "files").iterdir():
        dst = TARGET / src.name
        if src.is_dir():  # 例：dashboard/（即時儀表板）
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"  ✔ {dst}\\")
            continue
        if dst.exists() and dst.read_bytes() != src.read_bytes():
            shutil.copy2(dst, dst.with_name(f"{dst.stem}.bak-{STAMP}{dst.suffix}"))
            print(f"  已備份舊的 {dst.name}")
        shutil.copy2(src, dst)
        print(f"  ✔ {dst}")


def set_env(secrets: dict) -> None:
    step("寫入使用者環境變數")
    for k, v in secrets.items():
        subprocess.run(["setx", k, v], check=True, capture_output=True)
        os.environ[k] = v
        print(f"  ✔ {k}")
    if not secrets:
        print("  ⚠ secrets.env 沒有金鑰，略過")


def install_skill() -> None:
    step(f"安裝 skill 到 {SKILL_DST}")
    if SKILL_DST.exists():
        backup = SKILL_DST.with_name(f"deepseek-orchestrator.bak-{STAMP}")
        shutil.move(str(SKILL_DST), backup)
        print(f"  已備份舊的 skill 到 {backup}")
    shutil.copytree(KIT / "skill", SKILL_DST)
    print("  ✔ 完成")


def server_entries(secrets: dict) -> dict:
    py = sys.executable
    return {
        "deepseek_swarm": {"command": py, "args": [str(TARGET / "deepseek_swarm.py")],
                           "env": {k: v for k, v in secrets.items() if k.startswith("DEEPSEEK")}},
        "cloudflare_image": {"command": py, "args": [str(TARGET / "cloudflare_image.py")],
                             "env": {k: v for k, v in secrets.items() if k.startswith("CF_")}},
    }


def configure_desktop(secrets: dict) -> None:
    step(f"設定 Claude 桌面 App：{DESKTOP_CFG}")
    cfg = {}
    if DESKTOP_CFG.exists():
        text = DESKTOP_CFG.read_text(encoding="utf-8-sig")
        cfg = json.loads(text) if text.strip() else {}
        shutil.copy2(DESKTOP_CFG, DESKTOP_CFG.with_name(f"claude_desktop_config.bak-{STAMP}.json"))
        print("  已備份原設定檔")
    else:
        DESKTOP_CFG.parent.mkdir(parents=True, exist_ok=True)
    cfg.setdefault("mcpServers", {}).update(server_entries(secrets))
    DESKTOP_CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  ✔ 已加入 deepseek_swarm、cloudflare_image")


def configure_cli(secrets: dict) -> None:
    claude = shutil.which("claude")
    step("設定 Claude Code CLI")
    if not claude:
        print("  （沒有 claude CLI，略過；桌面 App 的 Code 分頁用上面的設定就夠）")
        return
    for name, e in server_entries(secrets).items():
        subprocess.run([claude, "mcp", "remove", "--scope", "user", name], capture_output=True)
        cmd = [claude, "mcp", "add", "--scope", "user", name]
        for k, v in e["env"].items():
            cmd += ["-e", f"{k}={v}"]
        cmd += ["--", e["command"], *e["args"]]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(f"  {'✔' if r.returncode == 0 else '✘'} {name} {r.stderr.strip()}")


def check(secrets: dict) -> bool:
    step("檢查")
    ok = True
    v = sys.version_info
    print(f"  {'✔' if v >= (3, 10) else '✘'} Python {v.major}.{v.minor}（需要 3.10 以上）")
    ok &= v >= (3, 10)
    for mod in ("mcp", "openai", "httpx", "PIL"):
        found = importlib.util.find_spec(mod) is not None
        print(f"  {'✔' if found else '✘'} 套件 {mod}")
        ok &= found
    for f in ("deepseek_swarm.py", "ds.py", "wait_job.py", "cloudflare_image.py",
              "dashboard_events.py", "dashboard/ds_gui.py"):
        exists = (TARGET / f).exists()
        print(f"  {'✔' if exists else '✘'} {TARGET / f}")
        ok &= exists
    print(f"  {'✔' if (SKILL_DST / 'SKILL.md').exists() else '✘'} skill")
    node = shutil.which("node")
    print(f"  {'✔ Node 已安裝' if node else '⚠ 沒有 Node：JavaScript 任務的測試會失敗，其他照常（winget install OpenJS.NodeJS.LTS）'}")
    key = secrets.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
    if key and importlib.util.find_spec("openai"):
        try:
            from openai import OpenAI
            base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            OpenAI(api_key=key, base_url=base, timeout=20).models.list()
            print("  ✔ DeepSeek 金鑰可用")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✘ DeepSeek 連線失敗：{exc}")
            ok = False
    else:
        print("  ✘ 沒有 DEEPSEEK_API_KEY")
        ok = False
    if importlib.util.find_spec("mcp"):
        r = subprocess.run([sys.executable, "-c", "import deepseek_swarm, cloudflare_image"],
                           cwd=TARGET, capture_output=True, text=True, timeout=60,
                           env={**os.environ, **secrets})
        print(f"  {'✔' if r.returncode == 0 else '✘'} 伺服器程式可載入" + ("" if r.returncode == 0 else f"：{r.stderr[-400:]}"))
        ok &= r.returncode == 0
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    secrets = load_secrets()
    if not args.check:
        pip_install()
        copy_files()
        set_env(secrets)
        install_skill()
        configure_desktop(secrets)
        configure_cli(secrets)
    ok = check(secrets)
    print()
    if ok:
        print("全部完成。請「完全結束」Claude App（包含系統匣圖示）再重開，新對話就能用 DeepSeek 工蜂。")
    else:
        print("有 ✘ 的項目需要處理。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
