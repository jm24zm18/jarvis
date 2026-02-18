---
agent_id: security_reviewer
allowed_tools:
  - echo
  - exec_host
  - web_search
  - skill_list
  - skill_read
  - skill_write
risk_tier: high
max_actions_per_step: 6
allowed_paths:
  - /home/justin/jarvis
  - /tmp
can_request_privileged_change: true
---
