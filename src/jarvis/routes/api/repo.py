import asyncio
import logging
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException

from jarvis.auth.dependencies import require_auth

router = APIRouter()
logger = logging.getLogger(__name__)
REPO_ROOT = Path.cwd()

def validate_branch(branch: str) -> bool:
    """Strictly validate branch names to avoid command injection or invalid refs."""
    if ".." in branch or branch.startswith("-"):
        return False
    return bool(re.match(r"^[a-zA-Z0-9_\-\.\/]+$", branch))

async def run_git(*args: str) -> tuple[str, str, int]:
    """Execute git safely as an argument array from the workspace root."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode("utf-8"), stderr.decode("utf-8"), proc.returncode or 0
    except Exception as e:
        logger.error("repo.git_execution_failed error=%s args=%s", str(e), args)
        raise HTTPException(status_code=500, detail="Internal Git error") from e


@router.get("/status")
async def repo_status(admin: Annotated[dict[str, Any], Depends(require_auth)]) -> dict[str, Any]:
    stdout, _, code = await run_git("status", "--porcelain=v1", "-b")
    if code != 0:
        raise HTTPException(status_code=500, detail="Failed to retrieve git status")
    
    lines = stdout.splitlines()
    branch_line = lines[0] if lines else ""
    files = lines[1:] if len(lines) > 1 else []
    
    branch = ""
    upstream = ""
    ahead = 0
    behind = 0
    
    if branch_line.startswith("## "):
        parts = branch_line[3:].split("...")
        branch = parts[0].strip()
        if len(parts) > 1:
            up_parts = parts[1].split(" [")
            upstream = up_parts[0].strip()
            if len(up_parts) > 1:
                state = up_parts[1].rstrip("]")
                if "ahead " in state:
                    ahead_chunk = state.split("ahead ")[1].split(",")[0].split(" ")[0]
                    ahead = int(ahead_chunk) if ahead_chunk.isdigit() else 0
                if "behind " in state:
                    behind_chunk = state.split("behind ")[1].split(",")[0].split(" ")[0]
                    behind = int(behind_chunk) if behind_chunk.isdigit() else 0
                    
    staged = []
    unstaged = []
    untracked = []
    conflicted = []
    
    for obj in files:
        if len(obj) < 4:
            continue
        index_stat = obj[0]
        work_stat = obj[1]
        path = obj[3:]
        
        if index_stat in ("U", "A", "D") and work_stat in ("U", "A", "D"):
            conflicted.append(path)
            continue
            
        if index_stat in ("M", "A", "D", "R", "C"):
            staged.append(path)
            
        if work_stat in ("M", "D"):
            unstaged.append(path)
            
        if index_stat == "?" and work_stat == "?":
            untracked.append(path)
            
    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicted": conflicted,
        "is_clean": not any([staged, unstaged, untracked, conflicted])
    }

@router.get("/log")
async def repo_log(
    admin: Annotated[dict[str, Any], Depends(require_auth)],
    limit: int = 50,
) -> list[dict[str, str]]:
    stdout, _, code = await run_git(
        "log", f"-n{limit}", "--pretty=format:%H|%h|%s|%an|%ae|%aI"
    )
    if code != 0:
        return []
    
    log_entries = []
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) >= 6:
            log_entries.append({
                "sha": parts[0],
                "short_sha": parts[1],
                "subject": parts[2],
                "author_name": parts[3],
                "author_email": parts[4],
                "authored_at": parts[5]
            })
    return log_entries

@router.get("/branches")
async def repo_branches(
    admin: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, Any]:
    stdout, _, code = await run_git(
        "branch", "-a", "--format=%(refname:short)|%(HEAD)"
    )
    if code != 0:
        raise HTTPException(status_code=500, detail="Failed to get branches")
    
    local: list[str] = []
    remote: list[str] = []
    current = ""
    
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 2:
            continue
        name, is_head = parts[0], parts[1]
        
        if is_head == "*":
            current = name
            
        if name.startswith("origin/"):
            remote.append(name.replace("origin/", "", 1))
        else:
            local.append(name)
            
    return {
        "current": current,
        "local": sorted(list(set(local))),
        "remote": sorted(list(set(remote)))
    }

@router.get("/diff")
async def repo_diff(
    admin: Annotated[dict[str, Any], Depends(require_auth)],
    mode: str = "working",
    path: str | None = None,
) -> str:
    args = ["diff"]
    if mode == "staged":
        args.append("--cached")
    
    if path:
        args.extend(["--", path])
        
    stdout, _, code = await run_git(*args)
    if code != 0:
        raise HTTPException(status_code=500, detail="Failed to compute diff")
    return stdout

@router.post("/checkout")
async def repo_checkout(
    admin: Annotated[dict[str, Any], Depends(require_auth)],
    branch: Annotated[str | None, Body()] = None,
    create_branch: Annotated[str | None, Body()] = None,
) -> dict[str, str]:
    if not branch and not create_branch:
        raise HTTPException(status_code=400, detail="Must provide branch or create_branch")
    
    target = create_branch if create_branch else branch
    target = target or ""
    if not validate_branch(target):
        raise HTTPException(status_code=400, detail="invalid_branch")
        
    args = ["checkout"]
    if create_branch:
        args.append("-b")
    args.append(target)
    
    stdout, stderr, code = await run_git(*args)
    if code != 0:
        raise HTTPException(status_code=400, detail=f"Checkout failed: {stderr}")
        
    logger.info("repo.checkout target=%s created=%s", target, bool(create_branch))
    return {"status": "success"}

@router.post("/stage")
async def repo_stage(
    admin: Annotated[dict[str, Any], Depends(require_auth)],
    paths: Annotated[list[str] | None, Body()] = None,
    all: Annotated[bool, Body()] = False,
) -> dict[str, str]:
    if not paths and not all:
        raise HTTPException(status_code=400, detail="Must provide paths or all=true")
        
    args = ["add"]
    if all:
        args.append("--all")
    elif paths:
        # Prevent escaping workspace root
        clean_paths = [p for p in paths if not p.startswith("..")]
        args.extend(clean_paths)
        
    stdout, stderr, code = await run_git(*args)
    if code != 0:
        raise HTTPException(status_code=400, detail=f"Stage failed: {stderr}")
        
    logger.info("repo.stage all=%s paths=%s", all, len(paths) if paths else 0)
    return {"status": "success"}

@router.post("/unstage")
async def repo_unstage(
    paths: Annotated[list[str], Body(...)],
    admin: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, str]:
    if not paths:
        raise HTTPException(status_code=400, detail="Must provide paths")
        
    clean_paths = [p for p in paths if not p.startswith("..")]
    args = ["restore", "--staged"]
    args.extend(clean_paths)
    
    stdout, stderr, code = await run_git(*args)
    if code != 0:
        raise HTTPException(status_code=400, detail=f"Unstage failed: {stderr}")
        
    logger.info("repo.unstage paths=%s", len(paths))
    return {"status": "success"}

@router.post("/commit")
async def repo_commit(
    message: Annotated[dict[str, Any], Body(...)],
    admin: Annotated[dict[str, Any], Depends(require_auth)],
) -> dict[str, str]:
    msg_str = message.get("message", "")
    if not msg_str.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
        
    stdout, stderr, code = await run_git("commit", "-m", msg_str)
    if code != 0:
        if "nothing to commit" in stdout or "nothing to commit" in stderr:
            raise HTTPException(status_code=400, detail="nothing_to_commit")
        raise HTTPException(status_code=400, detail=f"Commit failed: {stderr}")
        
    logger.info("repo.commit message=%s", msg_str[:50])
    return {"status": "success"}

@router.post("/push")
async def repo_push(
    admin: Annotated[dict[str, Any], Depends(require_auth)],
    set_upstream: Annotated[dict[str, Any] | None, Body()] = None,
) -> dict[str, str]:
    if set_upstream is None:
        set_upstream = {"set_upstream": False}
        
    args = ["push"]
    
    if set_upstream.get("set_upstream"):
        # Get current branch
        stdout, _, code = await run_git("branch", "--show-current")
        if code == 0 and stdout.strip():
            args.extend(["-u", "origin", stdout.strip()])
            
    stdout, stderr, code = await run_git(*args)
    if code != 0:
        raise HTTPException(status_code=400, detail=f"push_failed: {stderr}")
        
    logger.info("repo.push upstream=%s", set_upstream.get("set_upstream", False))
    return {"status": "success"}
