---
agent_id: main
allowed_tools:
  - echo
  - session_list
  - session_history
  - session_send
  - web_search
  - exec_host
  - skill_list
  - skill_read
  - skill_write
  - update_persona
risk_tier: medium
max_actions_per_step: 12
allowed_paths:
  - /home/justin
  - /tmp
  - /usr/local/bin
  - /usr/bin
can_request_privileged_change: true
---
