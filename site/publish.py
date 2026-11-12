"""Puts the site on GitHub Pages: this folder goes to the root of the gh-pages branch, the phone page (ui/dist) to phone/.

Run it from the repository after ui\\scripts\\build.cmd: python site\\publish.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SKIP = {"publish.py", "__pycache__"}


def git(*args, cwd=ROOT):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def main():
    work = Path(tempfile.mkdtemp(prefix="piven-pages-")) / "pages"
    git("fetch", "origin", "gh-pages")
    git("worktree", "add", "--detach", str(work), "origin/gh-pages")
    try:
        for item in work.iterdir():
            if item.name != ".git":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
        for item in SITE.iterdir():
            if item.name not in SKIP:
                (shutil.copytree if item.is_dir() else shutil.copy2)(item, work / item.name)
        shutil.copytree(ROOT / "ui" / "dist", work / "phone")
        (work / ".nojekyll").write_text("", encoding="utf-8")
        git("add", "-A", cwd=work)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=work).returncode == 0:
            print("nothing changed")
            return
        git("commit", "--allow-empty-message", "-m", "", cwd=work)
        git("push", "origin", "HEAD:gh-pages", cwd=work)
        print("published: https://covriknapoly-glitch.github.io/piven-companion/")
    finally:
        git("worktree", "remove", "--force", str(work))


if __name__ == "__main__":
    main()
