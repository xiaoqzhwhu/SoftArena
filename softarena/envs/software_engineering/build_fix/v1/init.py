from __future__ import annotations
from pathlib import Path
from typing import Any

def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    project = workspace / "project"
    project.mkdir(parents=True, exist_ok=True)
    source = '#include <stdio.h>\nint add(int a, int b) { return a - b; }\nint main(void) { if (add(2, 3) != 5) return 1; puts("ok"); return 0; }\n'
    makefile = 'all:\n\tcc -Wall -Werror -o mathlib mathlib.c\ntest: all\n\t./mathlib\nclean:\n\trm -f mathlib\n'
    (project / "mathlib.c").write_text(source)
    (project / "Makefile").write_text(makefile)
    return {"task_id":task["task_id"],"difficulty":task["difficulty"],"prompt":task["prompt"].format(project_dir=str(project)),"workspace":str(workspace),"project_dir":str(project),"source_path":str(project/"mathlib.c")}
