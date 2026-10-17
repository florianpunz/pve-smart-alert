# Requirements traceability

Which tests and acceptance steps relate to each requirement of [REQUIREMENTS.md](../REQUIREMENTS.md), and which requirements no test covers.
Milestone M7 asks that every requirement have a passing test or a ticked acceptance step ([ROADMAP.md](../ROADMAP.md), M7, result 2); this table is the starting point for that check, not its result.
It is a snapshot: it is made again for the release, not brought up to date with every change. Whether an acceptance step has passed is recorded only in ROADMAP.md.

How the columns were made, on 2026-10-17:

- **Tests that cite it**: a test function whose code or a comment directly above it names the requirement ID, or whose name holds it written as `fr_507`. Found mechanically. A citation says that the test is about the requirement, not that it covers all of it.
- **Sections and modules that name it**: a heading comment of a test file, at the start of a line and followed by an empty line, that names the ID, cited by its file and line; and a test module whose docstring names it. The tests below such a heading are not attributed one by one, because a section can go on into tests about something else: read the section.
- **Tests found by topic**: for a requirement that the other columns leave thin, tests whose name and content were read by hand and that test what the requirement asks; a note in brackets says what part they cover.
- **Acceptance step**: the step of a milestone checklist in ROADMAP.md that verifies the requirement on a real host. Only steps that ROADMAP.md links to the requirement clearly are named; their state is in ROADMAP.md.

The column "Verification" repeats the method of REQUIREMENTS.md: T automated test, A acceptance step, I inspection.

## Requirements that no test covers

A requirement is listed here when no test cites it, no section or module names it, and no test was found by topic. Where it has an acceptance step, ROADMAP.md says whether that step has passed.

| ID | Verification | Acceptance step | What is missing |
| --- | --- | --- | --- |
| FR-204 | T | – | The tests read `/dev/nvme0` because the recorded scan names it, but none asserts that a namespace such as `/dev/nvme0n1` is never read |
| FR-504 | A | M1 step 3 | The routing check of the tool is tested with such a matcher (`test_mode_all_needs_every_rule`, test_routing.py), but whether the notification system of Proxmox VE matches it is only an acceptance step |
| NFR-02 | A | M7 result 5 | Only an acceptance step |
| NFR-06 | I | – | Inspection only; the package job of CI checks that no byte code is in the package, not that only the standard library is imported |
| NFR-07 | T, A | – | No test and no acceptance step measures a run with 24 drives |
| NFR-17 | A | M5 step 8 | Only an acceptance step |
| NFR-18 | T | – | No test measures the delay from a change in SMART data to the notification; it follows from the timer interval and the confirmation counts, which are tested separately |
| NFR-19 | I | – | Inspection only (the hard rules of CLAUDE.md) |
| NFR-21 | I | – | Inspection only |

## All requirements

| ID | Verification | Tests that cite it | Sections and modules that name it | Tests found by topic | Acceptance step |
| --- | --- | --- | --- | --- | --- |
| FR-101 | T, A | – | – | test_every_drive_of_a_node_is_found_once (test_discovery.py) | M2 step 1 |
| FR-102 | T | – | – | test_a_sata_drive_behind_megaraid_is_read_as_ata (test_discovery.py)<br>test_drives_behind_megaraid_show_controller_and_device_id (test_scan.py)<br>the MegaRAID scenarios of test_scenarios.py | – |
| FR-103 | T | test_the_hpe_probe_is_on_by_default (test_config.py) | section test_config.py, line 388: probe_cciss (FR-103, ADR 0032)<br>section test_doctor.py, line 1005: The line `probe` (FR-103, ADR 0032)<br>module test_probes.py | – | – |
| FR-104 | T | test_the_manual_pass_through_scenario (test_scenarios.py) | section test_config.py, line 248: [[discovery.device]] (FR-104)<br>section test_discovery.py, line 219: Manual devices (FR-104)<br>section test_discovery.py, line 636: Drives behind the other controllers, named by manual entries (FR-104) | – | M2 step 4 |
| FR-105 | T | test_the_path_is_not_part_of_the_identity (test_model.py)<br>test_the_megaraid_id_change_scenario (test_scenarios.py) | – | – | – |
| FR-106 | T | test_a_drive_reached_through_two_paths_is_kept_once (test_discovery.py)<br>test_a_drive_in_jbod_mode_is_kept_once_as_its_block_device (test_discovery.py)<br>test_a_drive_the_scan_lists_is_kept_over_the_probe (test_probes.py)<br>test_the_megaraid_jbod_scenario (test_scenarios.py) | – | – | – |
| FR-107 | T | – | section test_discovery.py, line 271: Filtering (FR-107) | – | – |
| FR-108 | T, A | – | section test_probes.py, line 472: What `scan` says about the controllers (FR-108, FR-109)<br>module test_scan.py | – | M2 steps 1 and 4 |
| FR-109 | T | – | section test_probes.py, line 472: What `scan` says about the controllers (FR-108, FR-109)<br>module test_controllers.py | – | – |
| FR-110 | T, A | – | – | test_a_pool_on_a_partition_is_the_pool_of_the_host (test_discovery.py)<br>test_the_volume_group_is_read_from_the_device_mapper_name (test_discovery.py)<br>test_the_pools_of_guests_are_not_the_pools_of_the_host (test_discovery.py) | M2 step 1 |
| FR-201 | I, T | – | – | test_an_answer_that_is_not_json_is_unreadable (test_collect.py)<br>test_another_json_format_is_unreadable (test_collect.py) | – |
| FR-202 | T | test_a_drive_that_does_not_answer_is_ended (test_collect.py) | – | – | – |
| FR-203 | T | test_a_recorded_ata_drive_is_read (test_collect.py)<br>test_a_standby_exit_is_standby_for_every_device_type (test_collect.py)<br>test_the_cciss_type_decides_over_the_protocol (test_collect.py)<br>test_the_type_of_another_controller_decides_over_the_protocol (test_collect.py)<br>test_a_cciss_drive_is_read_with_the_standby_check (test_collect.py)<br>test_a_drive_in_standby_keeps_its_state (test_planner.py)<br>test_three_standby_answers_in_a_row_are_not_failures (test_probes.py)<br>test_the_probe_does_not_wake_a_sleeping_drive (test_probes.py)<br>test_a_sleeping_drive_keeps_the_probe_going (test_probes.py)<br>test_the_manual_pass_through_scenario (test_scenarios.py) | – | – | – |
| FR-204 | T | – | – | – | – |
| FR-205 | T | – | section test_discovery.py, line 713: When parts of the host fail (FR-205) | – | M2 step 4 |
| FR-206 | T | test_a_check_without_input_is_not_applicable (test_checks.py)<br>test_a_snapshot_knows_only_what_it_is_given (test_model.py)<br>test_missing_sections_leave_the_values_out (test_parsers.py) | section test_checks.py, line 71: The model: applicability, missing data, severities (FR-301, FR-302, FR-206) | – | – |
| FR-301 | T | – | section test_checks.py, line 71: The model: applicability, missing data, severities (FR-301, FR-302, FR-206) | – | M3 step 1 |
| FR-302 | T | – | section test_checks.py, line 71: The model: applicability, missing data, severities (FR-301, FR-302, FR-206) | – | – |
| FR-303 | T | – | – | test_the_failed_health_verdict_is_critical (test_checks.py)<br>test_a_pre_fail_attribute_below_its_threshold_is_critical (test_checks.py)<br>test_spare_at_or_below_the_threshold_of_the_drive_is_critical (test_checks.py) | – |
| FR-304 | T | – | – | test_the_defect_counters_use_their_thresholds (test_checks.py) | M3 step 2 |
| FR-305 | T | – | – | test_the_worsening_rule_of_each_check_is_the_one_of_the_docs (test_checks.py)<br>test_a_worse_value_waits_for_the_cool_down_of_the_drive (test_planner.py) | – |
| FR-306 | T | test_an_event_without_a_baseline_produces_nothing (test_checks.py) | section test_planner.py, line 413: Events (FR-306) | – | – |
| FR-307 | T | test_wear_never_becomes_critical_by_default (test_checks.py) | – | – | – |
| FR-308 | T | test_the_confirmation_count_is_set_per_check (test_config.py)<br>test_the_temperature_needs_two_runs_before_it_is_notified (test_planner.py) | – | – | – |
| FR-309 | T | test_the_presence_checks_have_no_snapshot_to_answer_them (test_checks.py)<br>test_an_identity_is_stable_with_a_serial_number_or_a_wwn (test_model.py)<br>test_a_manual_cciss_entry_is_not_forgotten_with_the_probe_off (test_planner.py) | section test_planner.py, line 493: Drives that disappear (FR-309) | – | M4 step 7 |
| FR-310 | T | test_an_unreadable_drive_is_reported_after_two_runs (test_acceptance_m4.py)<br>test_the_presence_checks_have_no_snapshot_to_answer_them (test_checks.py) | section test_planner.py, line 597: Drives that stop answering (FR-310) | – | – |
| FR-311 | T | – | – | test_switched_off_smart_is_a_notice_that_names_the_command (test_checks.py) | – |
| FR-312 | T, A | – | module test_wear.py | – | M2 step 2 |
| FR-401 | T, A | – | – | test_an_empty_file_gives_the_defaults (test_config.py)<br>test_a_missing_file_gives_the_defaults (test_config.py) | M3, the acceptance on `pve1` (the absence of the file) |
| FR-402 | T | test_the_margin_of_the_spare_check_can_be_set_to_zero (test_checks.py) | section test_config.py, line 526: The check overrides of [checks."<id>"] (ADR 0011, FR-402) | – | M3 step 3 |
| FR-403 | T | – | section test_config.py, line 717: The per-drive overrides of [[drive]] (ADR 0011, FR-403)<br>section test_discovery.py, line 797: The per-drive overrides (FR-403) | – | M3 step 3 |
| FR-404 | T | test_config_show_names_the_origin_of_each_value (test_check_command.py)<br>test_the_confirmation_count_is_set_per_check (test_config.py) | section test_config.py, line 869: The settings of the notification policy (FR-404, ADR 0009) | – | – |
| FR-405 | T | – | module test_check_command.py | test_an_unknown_section_is_an_error (test_config.py)<br>test_the_line_of_an_unknown_key_is_reported (test_config.py)<br>test_a_wrong_type_is_an_error (test_config.py)<br>test_invalid_toml_is_an_error (test_config.py) | M3 step 4 |
| FR-406 | T | test_the_dry_run_uses_the_last_good_configuration (test_check_command.py)<br>test_the_dry_run_names_the_built_in_defaults_without_a_last_good_configuration (test_check_command.py)<br>test_config_show_works_with_an_invalid_file (test_check_command.py)<br>test_an_unusable_configuration_warns_and_a_run_continues (test_doctor.py) | section test_config.py, line 804: The last good configuration (ADR 0011, FR-406) | – | M3 step 4 |
| FR-407 | T | – | module test_check_command.py | – | – |
| FR-408 | T | test_config_show_lists_the_conditions_of_the_tool (test_check_command.py) | section test_config.py, line 553: The enabled state of a condition of the tool (ADR 0031, FR-408)<br>section test_controllers.py, line 528: Switching the condition off (FR-408, ADR 0031) | – | – |
| FR-501 | A | – | – | test_severity_mapping_follows_the_decision_record (test_model.py) | M1 step 2 |
| FR-502 | T, A | test_a_drive_message_carries_the_fields_of_the_drive (test_render.py) | – | – | M1 step 3 |
| FR-503 | T | test_a_drive_behind_a_raid_controller_names_controller_and_device_id (test_render.py)<br>test_a_drive_message_carries_the_fields_of_the_drive (test_render.py)<br>test_the_notifications_of_the_tool (test_routing.py) | – | – | – |
| FR-504 | A | – | – | – | M1 step 3 |
| FR-505 | T, A | – | – | test_the_fallback_takes_over_and_names_the_reason (test_transports.py) (the fallback, not the subject or the recipient)<br>test_mail_is_handed_to_the_mail_command (test_transports.py) | M1 step 4 |
| FR-506 | T | – | – | test_auto_builds_both_transports (test_transports.py)<br>test_mail_builds_the_mail_transport (test_transports.py)<br>test_the_bridge_builds_the_bridge_transport (test_transports.py)<br>test_the_transport_can_be_selected (test_config.py) | – |
| FR-507 | T | test_a_drive_behind_a_raid_controller_names_controller_and_device_id (test_render.py)<br>test_a_drive_behind_an_hpe_controller_names_controller_and_device_id (test_render.py) | – | test_the_body_holds_what_fr_507_asks_for (test_render.py) | – |
| FR-508 | T | test_the_subject_names_severity_host_drive_and_finding (test_render.py) | – | – | – |
| FR-509 | T | – | section test_planner.py, line 151: A condition appears (FR-509) | – | M4 step 3 |
| FR-510 | T | – | section test_planner.py, line 281: Nothing changed and the reminder interval has passed (FR-510) | – | M4 steps 2 and 4 |
| FR-511 | T | – | section test_planner.py, line 206: Severity rises (FR-511) | – | M4 step 5 |
| FR-512 | T | – | section test_planner.py, line 223: Value worsens at the same severity (FR-512) | – | – |
| FR-513 | T | – | section test_planner.py, line 348: The condition clears (FR-513) | – | M4 step 6 |
| FR-514 | T | – | section test_planner.py, line 673: Grouping (FR-514, FR-515, NFR-10) | – | – |
| FR-515 | T | – | section test_planner.py, line 673: Grouping (FR-514, FR-515, NFR-10) | – | M4 step 8 |
| FR-516 | T, A | – | section test_planner.py, line 755: The first run (FR-516) | – | M4 steps 1 and 10 |
| FR-517 | T | test_a_notification_that_fails_is_sent_on_the_next_run (test_acceptance_m4.py) | section test_planner.py, line 829: Delivery and state (FR-517)<br>module test_planner.py | – | – |
| FR-518 | T | test_a_missing_smartctl_is_a_problem_of_the_tool (test_acceptance_m4.py)<br>test_an_mpi3mr_controller_raises_the_condition_and_recovers (test_controllers.py) | section test_planner.py, line 875: Problems of the tool itself (FR-518)<br>module test_tool_conditions.py | – | – |
| FR-519 | A | – | – | test_a_failure_is_reported_to_root (test_report_failure.py)<br>test_a_second_failure_on_the_same_day_sends_nothing (test_report_failure.py) (both with a stand-in mail command and journal) | M5 step 6 |
| FR-520 | T, A | test_a_name_of_proxmox_leads_back_to_the_severity_of_the_tool (test_model.py) | – | the tests of test_test_notification.py | M1 step 2, M2 step 5 |
| FR-601 | T | test_the_dry_run_changes_nothing (test_acceptance_m4.py) | module test_check_command.py | – | M3 step 1 |
| FR-602 | T | test_status_shows_the_active_conditions_as_json (test_acceptance_m4.py) | – | – | M4 step 9 |
| FR-603 | T, A | test_the_controllers_are_read_from_the_sysfs_it_is_given (test_doctor.py) | section test_doctor.py, line 1141: The state file (FR-603)<br>section test_doctor.py, line 1183: Proxmox VE and smartd (FR-603, ADR 0002, ADR 0012)<br>module test_doctor.py | – | M1 step 5, M2 step 5 |
| FR-604 | T | – | module test_dump_fixture.py | – | M2 step 3 |
| FR-605 | T | test_a_second_run_while_one_holds_the_lock_is_skipped (test_acceptance_m4.py) | – | – | – |
| FR-606 | T | test_a_run_logs_one_summary_line (test_acceptance_m4.py)<br>test_without_a_terminal_there_is_no_progress (test_scan.py) | – | – | – |
| FR-607 | T | test_the_ten_steps_of_m4 (test_acceptance_m4.py)<br>test_a_notification_that_fails_is_sent_on_the_next_run (test_acceptance_m4.py)<br>test_a_run_that_cannot_take_its_lock_fails (test_check_command.py) | – | – | – |
| FR-701 | A | – | – | the tests of test_install_script.py (`install.sh` against a stand-in release, not on a host) | M5 step 1 |
| FR-702 | A | – | – | test_the_timer_runs_3_minutes_after_boot_and_then_every_30_minutes (test_units.py) (the unit, not a running host) | M5 steps 2 and 3 |
| FR-703 | A | – | – | test_the_timer_runs_3_minutes_after_boot_and_then_every_30_minutes (test_units.py) (`OnBootSec`, not a reboot) | M5 step 4 |
| FR-704 | A | – | – | test_a_state_of_an_earlier_build_is_read_and_continued (test_scenarios.py) (the state format, not the upgrade of the package) | M5 step 5 |
| FR-705 | T, A | – | – | `scripts/package-test.sh` in the package job of CI: installs, purges and checks that nothing is left | M1 step 6, M5 step 7 |
| NFR-01 | A, T | – | – | the step "The dependencies are the ones the tool needs" of the package job of CI | M1 step 1 |
| NFR-02 | A | – | – | – | M7 result 5 |
| NFR-03 | I, T | – | – | test_the_service_is_sandboxed_as_adr_0025_decided (test_units.py) (what the service may write)<br>`scripts/package-test.sh` (installed files and what is left after a purge) | – |
| NFR-04 | I, T | – | – | test_a_type_that_writes_to_the_drive_is_refused (test_config.py)<br>test_a_type_that_writes_to_the_drive_never_reaches_smartctl (test_discovery.py) (the one known writing case) | – |
| NFR-05 | T, A | – | – | test_the_fallback_takes_over_and_names_the_reason (test_transports.py) | M1 step 4 |
| NFR-06 | I | – | – | – | – |
| NFR-07 | T, A | – | – | – | – |
| NFR-08 | T | – | – | test_priority_and_run_time_are_limited (test_units.py) (`TimeoutStartSec=15min`) | – |
| NFR-09 | I, A | – | – | test_priority_and_run_time_are_limited (test_units.py) (`Nice`, I/O class and priority) | – |
| NFR-10 | T | test_the_tool_has_its_own_message_besides_the_drives (test_planner.py) | section test_planner.py, line 673: Grouping (FR-514, FR-515, NFR-10) | – | – |
| NFR-11 | T | test_a_failed_write_leaves_the_previous_file (test_state.py) | module test_state.py | – | – |
| NFR-12 | T | test_a_corrupt_state_file_is_set_aside_and_reported_once (test_acceptance_m4.py)<br>test_a_reset_state_is_mentioned_in_the_summary (test_planner.py)<br>test_a_corrupt_file_is_set_aside (test_state.py) | module test_state.py | – | M4 step 10 |
| NFR-13 | I, T | test_the_file_is_readable_by_root_only (test_state.py) | – | test_arguments_are_not_interpreted_by_a_shell (test_process.py) | – |
| NFR-14 | T | test_the_file_is_readable_by_root_only (test_state.py) | module test_dump_fixture.py<br>module test_fixtures.py | test_no_fixture_holds_a_real_identifier (test_fixtures.py)<br>test_all_devices_are_written_anonymized (test_dump_fixture.py)<br>test_nothing_is_written_when_a_real_value_would_be_left (test_dump_fixture.py) | M2 step 3 |
| NFR-15 | T | – | module test_planner.py | – | – |
| NFR-16 | I, T | – | module test_hardware_support.py | – | – |
| NFR-17 | A | – | – | – | M5 step 8 |
| NFR-18 | T | – | – | – | – |
| NFR-19 | I | – | – | – | – |
| NFR-20 | T | test_every_fixture_has_a_recorded_source (test_fixtures.py) | – | test_a_missing_license_identifier_is_reported, (test_check_hygiene.py) with `make hygiene` in CI | – |
| NFR-21 | I | – | – | – | – |
| NFR-22 | T | – | – | `make check` in CI, which runs ruff and mypy in strict mode; not a test | – |
