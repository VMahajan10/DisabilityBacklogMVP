"""Load versioned prompt files from /prompts/<name>/<version>.md.

File format: a front-matter block delimited by '---' lines with `name`, `version`, `description`,
then a `## system` section and a `## user` section. User section uses {placeholders}.
"""
import hashlib
import re
from dataclasses import dataclass

from app import config


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    sha: str
    system: str
    user_template: str

    def render_user(self, **kwargs) -> str:
        return self.user_template.format(**kwargs)


def latest_version(name: str) -> str:
    versions = sorted(p.stem for p in (config.PROMPTS_DIR / name).glob("v*.md"))
    if not versions:
        raise FileNotFoundError(f"No prompt versions for {name}")
    return max(versions, key=lambda v: int(v[1:]))


def load_prompt(name: str, version: str | None = None) -> Prompt:
    version = version or latest_version(name)
    raw = (config.PROMPTS_DIR / name / f"{version}.md").read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"Prompt {name}/{version} missing front-matter")
    body = m.group(2)
    sys_m = re.search(r"^## system\n(.*?)(?=^## user\n)", body, re.S | re.M)
    usr_m = re.search(r"^## user\n(.*)$", body, re.S | re.M)
    if not sys_m or not usr_m:
        raise ValueError(f"Prompt {name}/{version} needs '## system' and '## user' sections")
    return Prompt(
        name=name, version=version, sha=hashlib.sha256(raw.encode()).hexdigest(),
        system=sys_m.group(1).strip(), user_template=usr_m.group(1).strip(),
    )
