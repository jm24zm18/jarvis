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
max_actions_per_step: 8
allowed_paths:
  - /home/justin/jarvis
  - /tmp
can_request_privileged_change: true
---
