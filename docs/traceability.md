# Requirements traceability

Which test or acceptance step verifies each requirement of [REQUIREMENTS.md](../REQUIREMENTS.md), and which requirements have neither yet.
Milestone M7 asks that every requirement have a passing test or a ticked acceptance step ([ROADMAP.md](../ROADMAP.md), M7, result 2); this table is the starting point for that check, not its result.
It is a snapshot: it is made again for the release, not brought up to date with every change.

How the columns were made, on 2026-10-17, from the branch of slice 6 of M6:

- **Tests that cite it**: a test function whose code, a comment directly above it, or the heading comment of its section names the requirement ID; or, where no single test does, the module text of a test file. Found mechanically. A citation says that the test is about the requirement, not that it covers all of it.
- **Tests found by topic**: for a requirement that no test cites, tests whose name and content were read by hand and that test what the requirement asks. Nothing is listed where nothing was found.
- **Acceptance step**: the step of a milestone checklist in ROADMAP.md that verifies the requirement on a real host, and whether ROADMAP.md records it as passed. Only steps that ROADMAP.md links to a requirement clearly are named.

The column "Verification" repeats the method of REQUIREMENTS.md: T automated test, A acceptance step, I inspection.

## Requirements without a test or a passed acceptance step

| ID | Verification | What is missing |
| --- | --- | --- |
| FR-204 | T | No test cites it. The tests read `/dev/nvme0` because the recorded scan names it, but none asserts that a namespace such as `/dev/nvme0n1` is never read |
| FR-701 | A | M5 step 1, one-command installation on the cluster: open |
| FR-703 | A | M5 step 4, runs resume after a reboot: open |
| NFR-02 | A | M7 result 5, every supported Proxmox VE 9.x release: open |
| NFR-03 | I, T | No test of the host footprint beyond what the package test checks: the installed files and what is left after a purge |
| NFR-04 | I, T | No test asserts that every call of smartctl only reads; the refusal of the JMicron types in `[[discovery.device]]` (`test_a_type_that_writes_to_the_drive_is_refused`) covers one case |
| NFR-06 | I | Inspection only; the package job of CI checks that no byte code is in the package, not that only the standard library is imported |
| NFR-07 | T, A | No test and no acceptance step measures a run with 24 drives |
| NFR-17 | A | M5 step 8, quorum loss: open (Q-N5) |
| NFR-18 | T | No test measures the delay from a change in SMART data to the notification; it follows from the timer interval and the confirmation counts, which are tested separately |
| NFR-19 | I | Inspection only (the hard rules of CLAUDE.md) |
| NFR-21 | I | Inspection only |

## All requirements

| ID | Verification | Tests that cite it | Tests found by topic | Acceptance step |
| --- | --- | --- | --- | --- |
| FR-101 | T, A | – | `test_every_drive_of_a_node_is_found_once` (test_discovery.py) | M2 step 1, passed on the test cluster on 2026-10-12 |
| FR-102 | T | – | `test_the_pass_through_types_of_megaraid_reach_smartctl` (test_discovery.py)<br>`test_drives_behind_megaraid_show_controller_and_device_id` (test_scan.py)<br>the MegaRAID scenarios of tests/unit/test_scenarios.py | – |
| FR-103 | T | `test_the_hpe_probe_is_on_by_default` (test_config.py)<br>`test_the_hpe_probe_can_be_switched_off` (test_config.py)<br>`test_the_hpe_probe_takes_a_boolean` (test_config.py)<br>`test_the_hpe_probe_survives_a_round_trip` (test_config.py)<br>`test_the_exclude_rules_are_read` (test_config.py)<br>`test_exclude_rules_can_be_written_as_tables` (test_config.py)<br>and 9 more | – | – |
| FR-104 | T | `test_there_are_no_manual_devices_by_default` (test_config.py)<br>`test_manual_devices_are_read_in_their_order` (test_config.py)<br>`test_a_manual_device_that_is_not_one_is_an_error` (test_config.py)<br>`test_every_documented_pass_through_type_is_accepted` (test_config.py)<br>`test_a_type_that_writes_to_the_drive_is_refused` (test_config.py)<br>`test_manual_devices_must_be_tables` (test_config.py)<br>and 6 more | – | – |
| FR-105 | T | `test_the_path_is_not_part_of_the_identity` (test_model.py)<br>`test_the_megaraid_id_change_scenario` (test_scenarios.py) | – | – |
| FR-106 | T | `test_a_drive_reached_through_two_paths_is_kept_once` (test_discovery.py)<br>`test_a_drive_in_jbod_mode_is_kept_once_as_its_block_device` (test_discovery.py)<br>`test_a_drive_the_scan_lists_is_kept_over_the_probe` (test_probes.py)<br>`test_the_megaraid_jbod_scenario` (test_scenarios.py) | – | – |
| FR-107 | T | `test_an_excluded_drive_is_skipped_with_its_rule` (test_discovery.py)<br>`test_a_sleeping_drive_is_not_woken` (test_discovery.py)<br>`test_a_drive_on_a_remote_transport_is_not_read` (test_discovery.py)<br>`test_nvme_over_fabrics_is_remote` (test_discovery.py)<br>`test_a_device_that_is_not_a_disk_is_not_read` (test_discovery.py)<br>`test_a_drive_without_smart_is_skipped` (test_discovery.py)<br>and 9 more | – | – |
| FR-108 | T, A | `test_scan_names_the_controller_and_what_it_found` (test_probes.py)<br>`test_scan_names_a_smartpqi_controller_that_is_not_probed` (test_probes.py)<br>`test_scan_says_when_the_probe_is_switched_off` (test_probes.py) | – | – |
| FR-109 | T | `test_scan_names_the_controller_and_what_it_found` (test_probes.py)<br>`test_scan_names_a_smartpqi_controller_that_is_not_probed` (test_probes.py)<br>`test_scan_says_when_the_probe_is_switched_off` (test_probes.py) | – | – |
| FR-110 | T, A | – | `test_a_pool_on_a_partition_is_the_pool_of_the_host` (test_discovery.py)<br>`test_the_volume_group_is_read_from_the_device_mapper_name` (test_discovery.py)<br>`test_the_pools_of_guests_are_not_the_pools_of_the_host` (test_discovery.py) | M2 step 1, passed on the test cluster on 2026-10-12 (LVM only; the cluster has no ZFS) |
| FR-201 | I, T | – | `test_an_answer_that_is_not_json_is_unreadable` (test_collect.py)<br>`test_another_json_format_is_unreadable` (test_collect.py) | – |
| FR-202 | T | `test_a_drive_that_does_not_answer_is_ended` (test_collect.py) | – | – |
| FR-203 | T | `test_a_recorded_ata_drive_is_read` (test_collect.py)<br>`test_a_standby_exit_is_standby_for_every_device_type` (test_collect.py)<br>`test_the_cciss_type_decides_over_the_protocol` (test_collect.py)<br>`test_a_cciss_drive_is_read_with_the_standby_check` (test_collect.py)<br>`test_a_drive_in_standby_keeps_its_state` (test_planner.py)<br>`test_three_standby_answers_in_a_row_are_not_failures` (test_probes.py)<br>and 2 more | – | – |
| FR-204 | T | – | – | – |
| FR-205 | T | `test_a_failed_scan_still_reads_the_manual_devices` (test_discovery.py)<br>`test_a_scan_device_of_an_odd_form_is_not_passed_on` (test_discovery.py)<br>`test_without_lsblk_the_drives_are_still_monitored` (test_discovery.py)<br>`test_the_links_below_dev_disk_are_found` (test_discovery.py) | – | – |
| FR-206 | T | `test_a_healthy_drive_produces_no_findings` (test_checks.py)<br>`test_a_check_without_input_is_not_applicable` (test_checks.py)<br>`test_a_check_of_another_class_is_not_applicable` (test_checks.py)<br>`test_every_finding_has_one_severity_and_the_check_names_its_source` (test_checks.py)<br>`test_a_snapshot_knows_only_what_it_is_given` (test_model.py)<br>`test_missing_sections_leave_the_values_out` (test_parsers.py) | – | – |
| FR-301 | T | `test_a_healthy_drive_produces_no_findings` (test_checks.py)<br>`test_a_check_without_input_is_not_applicable` (test_checks.py)<br>`test_a_check_of_another_class_is_not_applicable` (test_checks.py)<br>`test_every_finding_has_one_severity_and_the_check_names_its_source` (test_checks.py) | – | – |
| FR-302 | T | `test_a_healthy_drive_produces_no_findings` (test_checks.py)<br>`test_a_check_without_input_is_not_applicable` (test_checks.py)<br>`test_a_check_of_another_class_is_not_applicable` (test_checks.py)<br>`test_every_finding_has_one_severity_and_the_check_names_its_source` (test_checks.py) | – | – |
| FR-303 | T | – | `test_the_failed_health_verdict_is_critical` (test_checks.py)<br>`test_a_pre_fail_attribute_below_its_threshold_is_critical` (test_checks.py)<br>`test_spare_at_or_below_the_threshold_of_the_drive_is_critical` (test_checks.py) | – |
| FR-304 | T | – | `test_the_defect_counters_use_their_thresholds` (test_checks.py) | – |
| FR-305 | T | – | `test_the_worsening_rule_of_each_check_is_the_one_of_the_docs` (test_checks.py)<br>`test_a_worse_value_waits_for_the_cool_down_of_the_drive` (test_planner.py) | – |
| FR-306 | T | `test_an_event_without_a_baseline_produces_nothing` (test_checks.py)<br>`test_an_old_counter_value_never_alerts` (test_planner.py)<br>`test_a_rising_counter_is_notified_and_its_baseline_moves` (test_planner.py)<br>`test_a_counter_that_keeps_rising_waits_for_the_event_cool_down` (test_planner.py)<br>`test_a_counter_below_its_baseline_lowers_it_silently` (test_planner.py)<br>`test_an_event_has_no_recovery_and_no_reminder` (test_planner.py)<br>and 2 more | – | – |
| FR-307 | T | `test_wear_never_becomes_critical_by_default` (test_checks.py) | – | – |
| FR-308 | T | `test_the_confirmation_count_is_set_per_check` (test_config.py)<br>`test_the_temperature_needs_two_runs_before_it_is_notified` (test_planner.py) | – | – |
| FR-309 | T | `test_the_presence_checks_have_no_snapshot_to_answer_them` (test_checks.py)<br>`test_an_identity_is_stable_with_a_serial_number_or_a_wwn` (test_model.py)<br>`test_a_drive_absent_for_two_runs_is_notified_once` (test_planner.py)<br>`test_a_returning_drive_is_not_announced` (test_planner.py)<br>`test_removable_usb_and_unstable_drives_are_exempt` (test_planner.py)<br>`test_the_conditions_of_a_missing_drive_are_frozen` (test_planner.py)<br>and 5 more | – | – |
| FR-310 | T | `test_an_unreadable_drive_is_reported_after_two_runs` (test_acceptance_m4.py)<br>`test_the_presence_checks_have_no_snapshot_to_answer_them` (test_checks.py)<br>`test_a_drive_without_usable_data_for_two_runs_is_unreadable` (test_planner.py)<br>`test_an_unreadable_drive_that_answers_again_recovers` (test_planner.py)<br>`test_the_conditions_of_an_unreadable_drive_are_frozen` (test_planner.py)<br>`test_a_device_that_never_answered_is_unreadable_by_its_path` (test_planner.py)<br>and 1 more | – | – |
| FR-311 | T | – | `test_switched_off_smart_is_a_notice_that_names_the_command` (test_checks.py) | – |
| FR-312 | T, A | The module text of `test_wear.py` names it; no single test | – | – |
| FR-401 | T, A | – | `test_an_empty_file_gives_the_defaults` (test_config.py)<br>`test_a_missing_file_gives_the_defaults` (test_config.py) | M3, passed on `pve1` and the cluster on 2026-10-12 |
| FR-402 | T | `test_the_margin_of_the_spare_check_can_be_set_to_zero` (test_checks.py)<br>`test_a_threshold_can_be_overridden_globally` (test_config.py)<br>`test_a_check_can_be_switched_off` (test_config.py)<br>`test_a_check_that_is_off_by_default_can_be_switched_on` (test_config.py) | – | – |
| FR-403 | T | `test_a_drive_entry_can_exclude_and_describe_a_drive` (test_config.py)<br>`test_a_drive_entry_can_name_another_detail_level` (test_config.py)<br>`test_a_drive_entry_needs_exactly_one_selector` (test_config.py)<br>`test_an_unknown_key_in_a_drive_entry_is_an_error` (test_config.py)<br>`test_a_drive_entry_can_override_a_check` (test_config.py)<br>`test_an_unknown_check_in_a_drive_entry_is_an_error` (test_config.py)<br>and 3 more | – | M3, passed on `pve1` and the cluster on 2026-10-12 |
| FR-404 | T | `test_config_show_names_the_origin_of_each_value` (test_check_command.py)<br>`test_the_policy_has_the_defaults_of_adr_0009` (test_config.py)<br>`test_every_setting_of_the_policy_can_be_changed` (test_config.py)<br>`test_a_reminder_left_out_keeps_its_default` (test_config.py)<br>`test_a_wrong_setting_of_the_policy_names_the_key` (test_config.py)<br>`test_a_wrong_reminder_names_the_key` (test_config.py)<br>and 6 more | – | – |
| FR-405 | T | The module text of `test_check_command.py` names it; no single test | – | – |
| FR-406 | T | `test_the_dry_run_uses_the_last_good_configuration` (test_check_command.py)<br>`test_the_dry_run_names_the_built_in_defaults_without_a_last_good_configuration` (test_check_command.py)<br>`test_config_show_works_with_an_invalid_file` (test_check_command.py)<br>`test_the_last_good_configuration_survives_a_round_trip` (test_config.py)<br>`test_without_a_last_good_configuration_there_are_the_defaults` (test_config.py)<br>`test_an_invalid_file_leads_to_the_last_good_configuration` (test_config.py)<br>and 3 more | – | M3, passed on `pve1` and the cluster on 2026-10-12 |
| FR-407 | T | The module text of `test_check_command.py` names it; no single test | – | – |
| FR-408 | T | `test_config_show_lists_the_conditions_of_the_tool` (test_check_command.py)<br>`test_a_condition_of_the_tool_can_be_switched_off` (test_config.py)<br>`test_every_condition_of_the_tool_is_on_by_default` (test_config.py)<br>`test_a_condition_of_the_tool_written_as_its_default_is_dropped` (test_config.py)<br>`test_a_condition_of_the_tool_takes_no_threshold` (test_config.py)<br>`test_a_condition_of_the_tool_cannot_be_set_for_one_drive` (test_config.py)<br>and 13 more | – | – |
| FR-501 | A | – | – | M1 step 2, passed on the test cluster on 2026-10-04 |
| FR-502 | T, A | `test_a_drive_message_carries_the_fields_of_the_drive` (test_render.py) | – | – |
| FR-503 | T | `test_a_drive_behind_a_raid_controller_names_controller_and_device_id` (test_render.py)<br>`test_a_drive_message_carries_the_fields_of_the_drive` (test_render.py)<br>`test_the_notifications_of_the_tool` (test_routing.py) | – | – |
| FR-504 | A | – | – | M1 step 3, passed on the test cluster on 2026-10-04 |
| FR-505 | T, A | – | `test_the_fallback_takes_over_and_names_the_reason` (test_transports.py) | M1 step 4, passed on the test cluster on 2026-10-04 |
| FR-506 | T | – | `test_the_primary_transport_is_used_when_it_works` (test_transports.py)<br>`test_a_missing_bridge_with_the_primary_transport_only` (test_tool_conditions.py)<br>`test_the_mail_transport_has_no_bridge_to_fail` (test_tool_conditions.py) | – |
| FR-507 | T | `test_a_drive_behind_a_raid_controller_names_controller_and_device_id` (test_render.py)<br>`test_a_drive_behind_an_hpe_controller_names_controller_and_device_id` (test_render.py) | – | – |
| FR-508 | T | `test_the_subject_names_severity_host_drive_and_finding` (test_render.py) | – | – |
| FR-509 | T | `test_a_new_condition_is_notified_once` (test_planner.py)<br>`test_the_temperature_needs_two_runs_before_it_is_notified` (test_planner.py)<br>`test_a_temperature_seen_once_is_forgotten` (test_planner.py)<br>`test_the_confirmation_count_comes_from_the_configuration` (test_planner.py) | – | M4 steps 1 to 10, passed on `pve1` on 2026-10-12 |
| FR-510 | T | `test_a_warning_is_reminded_after_seven_days` (test_planner.py)<br>`test_a_critical_condition_is_reminded_after_three_days` (test_planner.py)<br>`test_a_notice_is_never_reminded` (test_planner.py)<br>`test_the_reminder_intervals_come_from_the_configuration` (test_planner.py) | – | M4 steps 1 to 10, passed on `pve1` on 2026-10-12 |
| FR-511 | T | `test_a_rise_in_severity_is_notified_at_once` (test_planner.py) | – | M4 step 5, passed on `pve1` on 2026-10-12 |
| FR-512 | T | `test_a_worse_value_waits_for_the_cool_down_of_the_drive` (test_planner.py)<br>`test_a_gauge_does_not_worsen_below_the_next_severity` (test_planner.py)<br>`test_the_cool_down_counts_from_any_notification_about_the_drive` (test_planner.py) | – | – |
| FR-513 | T | `test_a_condition_absent_for_two_runs_recovers_once` (test_planner.py)<br>`test_a_value_that_flips_does_not_notify_again` (test_planner.py)<br>`test_recoveries_can_be_switched_off` (test_planner.py)<br>`test_the_clear_count_comes_from_the_configuration` (test_planner.py)<br>`test_a_check_switched_off_drops_its_condition_silently` (test_planner.py) | – | M4 step 6, passed on `pve1` on 2026-10-12 |
| FR-514 | T | `test_the_notifications_of_one_drive_are_one_message` (test_planner.py)<br>`test_more_drives_than_the_limit_are_one_summary` (test_planner.py)<br>`test_up_to_the_limit_each_drive_has_its_own_message` (test_planner.py)<br>`test_the_grouping_limit_comes_from_the_configuration` (test_planner.py)<br>`test_the_tool_has_its_own_message_besides_the_drives` (test_planner.py) | – | – |
| FR-515 | T | `test_the_notifications_of_one_drive_are_one_message` (test_planner.py)<br>`test_more_drives_than_the_limit_are_one_summary` (test_planner.py)<br>`test_up_to_the_limit_each_drive_has_its_own_message` (test_planner.py)<br>`test_the_grouping_limit_comes_from_the_configuration` (test_planner.py)<br>`test_the_tool_has_its_own_message_besides_the_drives` (test_planner.py) | – | M4 step 8, passed on `pve1` on 2026-10-12 |
| FR-516 | T, A | `test_the_first_run_sends_exactly_one_summary` (test_planner.py)<br>`test_the_first_run_without_findings_is_info` (test_planner.py)<br>`test_the_first_run_records_temperatures_without_waiting` (test_planner.py)<br>`test_the_first_run_summary_can_be_switched_off` (test_planner.py)<br>`test_a_reset_state_is_mentioned_in_the_summary` (test_planner.py) | – | M4 steps 1 and 10, passed on `pve1` on 2026-10-12 |
| FR-517 | T | `test_a_notification_that_fails_is_sent_on_the_next_run` (test_acceptance_m4.py)<br>`test_a_notification_that_was_not_handed_over_is_planned_again` (test_planner.py)<br>`test_a_first_run_whose_summary_failed_is_a_first_run_again` (test_planner.py)<br>`test_a_recovery_that_failed_is_sent_on_the_next_run` (test_planner.py)<br>`test_an_event_that_failed_keeps_its_baseline` (test_planner.py) | – | – |
| FR-518 | T | `test_a_missing_smartctl_is_a_problem_of_the_tool` (test_acceptance_m4.py)<br>`test_an_mpi3mr_controller_raises_the_condition_and_recovers` (test_controllers.py)<br>`test_a_condition_of_the_tool_follows_the_same_rules` (test_planner.py)<br>`test_the_planner_leaves_the_state_it_was_given_alone` (test_planner.py) | – | – |
| FR-519 | A | – | `test_a_failure_is_reported_to_root` (test_report_failure.py)<br>`test_a_second_failure_on_the_same_day_sends_nothing` (test_report_failure.py) | M5 step 6: passed on `pve1` on 2026-10-13 with an earlier failure reporter; open for the one on `main` |
| FR-520 | T, A | `test_a_name_of_proxmox_leads_back_to_the_severity_of_the_tool` (test_model.py) | – | – |
| FR-601 | T | `test_the_dry_run_changes_nothing` (test_acceptance_m4.py) | – | – |
| FR-602 | T | `test_status_shows_the_active_conditions_as_json` (test_acceptance_m4.py) | – | – |
| FR-603 | T, A | `test_the_controllers_are_read_from_the_sysfs_it_is_given` (test_doctor.py)<br>`test_without_a_state_file_the_next_run_is_a_first_run` (test_doctor.py)<br>`test_the_state_file_names_the_last_run` (test_doctor.py)<br>`test_a_last_run_that_could_not_deliver_warns` (test_doctor.py)<br>`test_a_corrupt_state_file_warns_and_is_left_alone` (test_doctor.py)<br>`test_the_version_of_proxmox_ve` (test_doctor.py)<br>and 5 more | – | – |
| FR-604 | T | The module text of `test_dump_fixture.py` names it; no single test | – | – |
| FR-605 | T | `test_a_second_run_while_one_holds_the_lock_is_skipped` (test_acceptance_m4.py) | – | – |
| FR-606 | T | `test_a_run_logs_one_summary_line` (test_acceptance_m4.py)<br>`test_without_a_terminal_there_is_no_progress` (test_scan.py) | – | – |
| FR-607 | T | `test_the_ten_steps_of_m4` (test_acceptance_m4.py)<br>`test_a_notification_that_fails_is_sent_on_the_next_run` (test_acceptance_m4.py)<br>`test_a_run_that_cannot_take_its_lock_fails` (test_check_command.py) | – | – |
| FR-701 | A | – | – | M5 step 1: open |
| FR-702 | A | – | `test_the_timer_runs_3_minutes_after_boot_and_then_every_30_minutes` (test_units.py) | M5 step 2: passed on `pve1` on 2026-10-13; open on the cluster |
| FR-703 | A | – | – | M5 step 4: open |
| FR-704 | A | – | – | M5 step 5: passed on `pve1` for the upgrades up to 0.5.0~dev3 (2026-10-16); open on the cluster |
| FR-705 | T, A | – | `scripts/package-test.sh` in the package job of CI: installs, purges and checks that nothing is left | M1 step 6, passed on 2026-10-04 with 0.1.0; M5 step 7: open |
| NFR-01 | A, T | – | – | M1 step 1, passed on 2026-10-04 with 0.1.0 |
| NFR-02 | A | – | – | M7 result 5: open |
| NFR-03 | I, T | – | – | – |
| NFR-04 | I, T | – | – | – |
| NFR-05 | T, A | – | `test_the_fallback_takes_over_and_names_the_reason` (test_transports.py) | M1 step 4, passed on 2026-10-04 |
| NFR-06 | I | – | – | – |
| NFR-07 | T, A | – | – | none recorded |
| NFR-08 | T | – | `test_priority_and_run_time_are_limited (`TimeoutStartSec=15min`)` (test_units.py) | – |
| NFR-09 | I, A | – | `test_priority_and_run_time_are_limited (`Nice`, I/O class and priority)` (test_units.py) | – |
| NFR-10 | T | `test_the_notifications_of_one_drive_are_one_message` (test_planner.py)<br>`test_more_drives_than_the_limit_are_one_summary` (test_planner.py)<br>`test_up_to_the_limit_each_drive_has_its_own_message` (test_planner.py)<br>`test_the_grouping_limit_comes_from_the_configuration` (test_planner.py)<br>`test_the_tool_has_its_own_message_besides_the_drives` (test_planner.py) | – | – |
| NFR-11 | T | `test_a_failed_write_leaves_the_previous_file` (test_state.py) | – | – |
| NFR-12 | T | `test_a_corrupt_state_file_is_set_aside_and_reported_once` (test_acceptance_m4.py)<br>`test_a_reset_state_is_mentioned_in_the_summary` (test_planner.py)<br>`test_a_corrupt_file_is_set_aside` (test_state.py) | – | – |
| NFR-13 | I, T | `test_the_file_is_readable_by_root_only` (test_state.py) | – | – |
| NFR-14 | T | `test_the_file_is_readable_by_root_only` (test_state.py) | – | – |
| NFR-15 | T | The module text of `test_planner.py` names it; no single test | – | – |
| NFR-16 | I, T | The module text of `test_hardware_support.py` names it; no single test | – | – |
| NFR-17 | A | – | – | M5 step 8: open (Q-N5) |
| NFR-18 | T | – | – | – |
| NFR-19 | I | – | – | – |
| NFR-20 | T | `test_every_fixture_has_a_recorded_source` (test_fixtures.py) | – | – |
| NFR-21 | I | – | – | – |
| NFR-22 | T | – | `make lint typecheck` in CI (ruff, mypy in strict mode); not a test | – |
