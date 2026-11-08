# Feature map

Each MCP tool and server route, and how a verifier proves it. Unit tests are in
`tests/test_mcp_server.py` and run against a fake remote server. They prove
what each tool sends and how it reads the reply. They never run a `server.py`
handler, so every route's server side is manual (steps refer to
`SKILL.md` part 2). One table, not a file per feature, because Jeff wants this
skill short.

## MCP tools (`mcp_server.py`)

All nine: `test_server_lists_exactly_the_nine_tools`,
`test_every_tool_sets_all_four_hints_as_booleans`,
`test_hints_match_what_each_handler_does`, and the probe's `tools/list` checks.

| Tool | Proved by | Manual step |
|---|---|---|
| `ps5_look` | `test_ps5_look_returns_screenshot_and_status`, `test_ps5_look_reports_server_error_without_image`, `test_ps5_look_tells_the_agent_when_remote_server_is_down`, `test_ps5_look_tells_the_agent_when_remote_server_times_out`, probe `ps5_look without server` | 3 |
| `ps5_play` | `test_ps5_play_sends_steps_and_returns_frames`, `test_ps5_play_reports_failure`, `test_ps5_play_rejects_unknown_button` | 7 |
| `ps5_press` | `test_ps5_press_sends_buttons_and_looks`, `test_ps5_press_without_look`, `test_ps5_press_reports_failure` | 7 |
| `ps5_type` | `test_ps5_type_sends_text_and_appends_hint`, `test_ps5_type_reports_failure` | 2, 7 |
| `ps5_home` | `test_ps5_home_goes_home_and_looks`, `test_ps5_home_reports_failure` | 2, 7 |
| `ps5_power` | `test_ps5_power_on_wakes`, `test_ps5_power_rest_sends_rest`, `test_ps5_power_rejects_unknown_state` | 7 |
| `psn_now_playing` | `test_psn_now_playing_returns_presence`, `test_psn_tools_turn_non_json_into_an_error` | 7 |
| `psn_library` | `test_psn_library_passes_query_limit_and_refresh` | 3 |
| `psn_store_search` | `test_psn_store_search_passes_query_and_limit` | 7 |

## Server routes (`server.py`)

| Route | Client side proved by | Server side |
|---|---|---|
| `GET /` | none | 1 |
| `GET /api/state` | `test_ps5_look_returns_screenshot_and_status` (status line) | 2 |
| `GET /api/activity` | none | 2, the page's Activity feed |
| `GET /api/debug` | none | 7 |
| `POST /api/sign-in` | none | 6 |
| `POST /api/link` | none | 6 |
| `GET /api/screen.jpg` | `ps5_look` tests | 2, 3 |
| `POST /api/press` | `ps5_press` tests, probe route check | 7. The page sends presses over `/ws`, not this route |
| `POST /api/text` | `ps5_type` tests, probe route check | 2, 7 |
| `POST /api/play` | `ps5_play` tests | 7 |
| `POST /api/action/home` | `ps5_home` tests, probe route check | 2, 7 |
| `POST /api/action/wake`, `rest` | `ps5_power` tests, probe route check | 7 |
| `POST /api/action/connect`, `disconnect` | none | 7 |
| `GET /api/psn/status` | none | 6 |
| `POST /api/psn/npsso` | none | 6 |
| `GET /api/psn/presence` | `psn_now_playing` tests | 7 |
| `GET /api/psn/library` | `psn_library` test | 3 |
| `GET /api/psn/store` | `psn_store_search` test | 7 |
| `GET /ws` | none | 2, held buttons and sticks on the page |
