# MeshCore → LXMF Encoding Reference

**Transport key:** `announce` = Reticulum announce (broadcast); `direct` = encrypted unicast; `propagated` = LXMF store-and-forward; `receipt` = Reticulum delivery confirmation; `—` = bridge-internal, no wire encoding.

**Field key:** `f[01]` = UTF-8 text (standard LXMF); `f[FB]` = msgpack app-data dict (CoreNet namespace); `f[FC]` = raw binary app-data.

**Destination naming** follows CoreNet convention: `meshcore.node.<hash>` (individual node), `meshcore.bridge.<hash>` (gateway/manifest), `meshcore.channel.<hash>` (group channel).

---

## Text Messaging

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_SEND_TXT_MSG` | `propagated` | `meshcore.node.<recipient_hash>` | `f[01]`: message text | Bridge intercepts when recipient is remote; falls through to radio for local |
| `CMD_SEND_CHANNEL_TXT_MSG` | `propagated` | `meshcore.channel.<channel_hash>` | `f[01]`: message text; `f[FB]`: `{ch_idx, ch_name}` | Channel hash derived from channel name + 16-byte secret via HKDF |
| `ContactMsgRecv` | `propagated` | `meshcore.node.<local_node_hash>` | `f[01]`: text; `f[FB]`: `{sender_prefix[8], path_len, ts}` | Synthesized inbound; bridge delivers to local radio as companion push |
| `ContactMsgRecvV3` | `propagated` | `meshcore.node.<local_node_hash>` | `f[01]`: text; `f[FB]`: `{sender_prefix[8], path_len, ts, snr}` | v3 adds SNR; prefer this encoding for all new bridge deployments |
| `ChannelMsgRecv` | `propagated` | `meshcore.channel.<channel_hash>` | `f[01]`: text; `f[FB]`: `{ch_idx, path_len, ts}` | Synthesized inbound from LXMF channel destination |
| `ChannelMsgRecvV3` | `propagated` | `meshcore.channel.<channel_hash>` | `f[01]`: text; `f[FB]`: `{ch_idx, path_len, ts, snr}` | Preferred over v1; SNR may be absent for LXMF-originated messages (set null) |
| `MsgSent` | `receipt` | — | Reticulum delivery confirmation | Transport-layer; bridge maps LXMF propagation receipt to `MsgSent` tag |
| `Ack` | `receipt` | — | Reticulum delivery confirmation | 4-byte tag echoed as LXMF message hash; no separate LXMF message needed |
| `MessagesWaiting` | `—` | — | — | Bridge-synthesized on LXMF propagation node poll; no wire representation |
| `NoMoreMsgs` | `—` | — | — | Bridge-synthesized after draining propagation queue |

---

## Advertisements & Discovery

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_SEND_SELF_ADVERT` | `announce` | `meshcore.node.<self_hash>` | Announce app_data: `{display_name[32], lat_udeg, lon_udeg, opt_in_flags}` | Triggers Reticulum announce; coordinates precision-reduced per CoreNet privacy policy |
| `Advertisement` | `announce` | `meshcore.node.<source_hash>` | Announce app_data: `{display_name[32], lat_udeg, lon_udeg, path_len}` | Remote node announce relayed by bridge; one announce per observed advertisement |
| `PushCodeNewAdvert` | `announce` | `meshcore.node.<source_hash>` | Announce app_data: `{display_name[32], lat_udeg, lon_udeg, opt_in_flags}` | Identical encoding to `Advertisement`; push variant triggers immediate re-announce |
| `AdvertResponse` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{tag[4], pubkey[32], node_type, display_name, lat_udeg, lon_udeg}` | Reply to explicit advert query; direct (not announce) since recipient is known |
| `ControlType::NodeDiscoverReq` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{mc_type: 0x80, region_tag}` | Query bridge manifest for nodes in a region |
| `ControlType::NodeDiscoverResp` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{mc_type: 0x90, nodes: [{pubkey, name, coords, last_seen}]}` | Paginated; multiple messages if result set large |

---

## Contact Management

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_GET_CONTACTS` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "contacts", region_tag, since_ts}` | Request manifest from bridge; paginated response as `Contact` sequence |
| `ContactStart` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{mc_type: 0x02, total_count}` | Bridge response header before streaming contact records |
| `Contact` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{mc_type: 0x03, pubkey[32], display_name, flags, path_len, lat_udeg, lon_udeg, last_seen, region_tag}` | One message per contact; manifest entry format per CoreNet README §Manifest |
| `ContactEnd` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{mc_type: 0x04, ts}` | Final message in contact list sequence |
| `CMD_ADD_UPDATE_CONTACT` | `—` | — | — | Local radio operation; bridge updates its manifest cache on receiving `Advertisement` |
| `CMD_REMOVE_CONTACT` | `—` | — | — | Local only; no Reticulum propagation of contact removal |
| `CMD_SHARE_CONTACT` | `direct` | `meshcore.node.<recipient_hash>` | `f[FB]`: `{pubkey[32], display_name, lat_udeg, lon_udeg}` | Explicit contact-card share; recipient adds to local radio via `CMD_ADD_UPDATE_CONTACT` |
| `CMD_EXPORT_CONTACT` | `—` | — | — | Produces URI locally; bridge may include URI as `f[01]` in a `CMD_SHARE_CONTACT` message |
| `CMD_IMPORT_CONTACT` | `—` | — | — | Local input; triggered by receiving a contact-share LXMF message |
| `ContactUri` | `direct` | `meshcore.node.<recipient_hash>` | `f[01]`: meshcore URI string | Simple text payload; recipient parses and imports |

---

## Device Info & Status

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_APP_START` | `—` | — | — | Local session init; no wire representation |
| `CMD_DEVICE_QUERY` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "device_info"}` | Query remote bridge's device capabilities |
| `SelfInfo` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{display_name, tx_power_dbm, freq_hz, bw_hz, sf, lat_udeg, lon_udeg}` | Response to remote device query; omit coords if opt_in_flags position bit unset |
| `DeviceInfo` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{firmware_ver, max_contacts, caps_flags, model, repeat_mode}` | Bridge exposes only non-sensitive capability fields; omit BLE PIN |
| `Battery` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{batt_mv, storage_kb}` | Sent only if telemetry `opt_in_flags` bit set |
| `StatusResponse` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{batt_mv, tx_queue_len, noise_floor_dbm, rssi_dbm, pkt_stats, snr, airtime_s, uptime_s}` | Response to `BinaryReqType::Status` relayed via bridge |
| `Stats` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{category: "core"\|"radio"\|"packets", data: bytes}` | Raw stats bytes preserved; category disambiguates sub-type |
| `CMD_SET_ADVERT_NAME` | `—` | — | — | Local only; triggers re-announce with new name |
| `CMD_SET_ADVERT_LATLON` | `—` | — | — | Local only; triggers re-announce with updated coords |
| `CMD_SET_RADIO_PARAMS` | `—` | — | — | Local radio config; not transmitted |
| `CMD_SET_RADIO_TX_POWER` | `—` | — | — | Local radio config |
| `CMD_SET_TUNING_PARAMS` | `—` | — | — | Local radio config |
| `CMD_GET_DEVICE_TIME` | `—` | — | — | Local serial query |
| `CMD_SET_DEVICE_TIME` | `—` | — | — | Local; bridge sync via NTP, not Reticulum |
| `CurrentTime` | `—` | — | — | Local response; bridge handles clock sync internally |
| `CMD_GET_BATT_AND_STORAGE` | `—` | — | — | Local query; result may be included in `StatusResponse` |

---

## Telemetry

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `BinaryReqType::Status` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "status"}` | Request wrapper; response is `StatusResponse` |
| `BinaryReqType::KeepAlive` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "keepalive", ts}` | Heartbeat; bridge replies with `Ok` |
| `BinaryReqType::Telemetry` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "telemetry"}` | Request LPP sensor data |
| `TelemetryResponse` | `direct` | `meshcore.node.<requester_hash>` | `f[FC]`: LPP-encoded sensor bytes; `f[FB]`: `{lpp_len}` | LPP format preserved as-is in `f[FC]`; metadata in `f[FB]` |
| `BinaryReqType::Mma` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "mma"}` | Request min/max/avg stats |
| `BinaryResponse (Mma)` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{response: "mma", entries: [{ch, type, min, max, avg}]}` | |
| `AnonReqType::Basic` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "basic_telemetry"}` | Anonymous clock/telemetry probe |

---

## Path & Network Diagnostics

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `PathDiscovery` | `direct` | `meshcore.node.<target_hash>` | `f[FB]`: `{mc_type: 0x34, probe_ts}` | Reticulum path establishment is also triggered; LXMF ping is supplemental |
| `PathDiscoveryResponse` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{mc_type: 0x8D, hop_count, path_bytes}` | Response carries hop count observed at LXMF layer; may differ from RF path |
| `PathUpdate` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{mc_type: 0x81, node_prefix[8], path_len, path_bytes}` | Notifies bridge of updated path for a known node |
| `CMD_RESET_PATH` | `—` | — | — | Local radio operation |
| `TraceData` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{hops: [{prefix[8], snr_db}]}` | Hop-by-hop SNR trace; LXMF-originated messages will lack MeshCore hop data |
| `LogData` | `direct` | `meshcore.node.<monitor_hash>` | `f[FB]`: `{snr_db, rssi_dbm}`; `f[FC]`: raw payload bytes | Sent only to monitoring destination; not broadcast |
| `BinaryReqType::Neighbours` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "neighbours"}` | Query bridge for RF neighbor table |
| `BinaryResponse (Neighbours)` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{response: "neighbours", entries: [{prefix[8], snr_db, last_seen_ts}]}` | |

---

## Channel Configuration

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_GET_CHANNEL` | `—` | — | — | Local serial query |
| `ChannelInfo` | `—` | — | — | Local response; 16-byte channel secret **must not** transit Reticulum in cleartext — distribute out-of-band |
| `CMD_SET_CHANNEL` | `—` | — | — | Local config only; channel secret distribution is out-of-band |
| `CMD_SET_FLOOD_SCOPE` | `—` | — | — | Local config |
| `SetFloodScope` | `—` | — | — | Local response |

---

## Access Control

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `BinaryReqType::Acl` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "acl"}` | Admin-authenticated request |
| `BinaryResponse (Acl)` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{response: "acl", entries: [{pubkey_prefix[8], perms_flags}]}` | Deliver only to authenticated admin identity |
| `AnonReqType::Regions` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "regions"}` | Query regional segment info from bridge manifest |
| `AnonReqType::Owner` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request: "owner"}` | Query bridge operator identity |
| `AutoaddConfig` | `—` | — | — | Local config; auto-add policy not transmitted |

---

## Admin & Session

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_SEND_LOGIN` | `—` | — | — | Local serial only; admin sessions are never proxied over Reticulum |
| `CMD_LOGOUT` | `—` | — | — | Local only |
| `LoginSuccess` | `—` | — | — | Local only |
| `LoginFailed` | `—` | — | — | Local only |
| `CMD_REBOOT` | `—` | — | — | Local only |
| `FactoryReset` | `—` | — | — | Local only; destructive — must not be remotely triggerable via bridge |

---

## Cryptographic Operations

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_SIGN_START` | `—` | — | — | Local signing session |
| `CMD_SIGN_DATA` | `—` | — | — | Local |
| `CMD_SIGN_FINISH` | `—` | — | — | Local |
| `SignStart` | `—` | — | — | Local response |
| `Signature` | `direct` | `meshcore.node.<recipient_hash>` | `f[FC]`: signature bytes (64 B Ed25519); `f[FB]`: `{signed_hash[32]}` | Signature may be attached to a substantive message rather than sent standalone |
| `PrivateKey` | `—` | — | — | **Never relay over Reticulum under any circumstances** |
| `CMD_EXPORT_PRIVATE_KEY` | `—` | — | — | Local only |
| `CMD_IMPORT_PRIVATE_KEY` | `—` | — | — | Local only |

---

## Custom Variables & Raw Data

| MeshCore Type | Transport | Destination | LXMF Fields | Notes |
|---|---|---|---|---|
| `CMD_GET_CUSTOM_VARS` | `—` | — | — | Local query |
| `CMD_SET_CUSTOM_VAR` | `—` | — | — | Local config; bridge may read `lxmf_hash` custom var to register node identity |
| `CustomVars` | `—` | — | — | Local response; bridge reads on init to obtain any user-set LXMF identity override |
| `CMD_SEND_RAW_DATA` | `direct` | `meshcore.node.<target_hash>` | `f[FC]`: raw bytes | Pass-through; use sparingly — type information is lost |
| `RawData` | `direct` | `meshcore.node.<local_node_hash>` | `f[FC]`: raw RF payload bytes | Bridge delivers raw inbound to local radio unchanged |
| `SendControlData` | `direct` | `meshcore.node.<target_hash>` | `f[FC]`: control payload bytes; `f[FB]`: `{ctrl_type}` | Control type byte preserved in metadata field |
| `ControlData` | `direct` | `meshcore.node.<local_node_hash>` | `f[FC]`: control payload bytes; `f[FB]`: `{ctrl_type}` | Inbound counterpart to `SendControlData` |
| `BinaryReq` | `direct` | `meshcore.bridge.<gateway_hash>` | `f[FB]`: `{request_type, tag[4], data}` | Generic wrapper; specific BinaryReqType entries above are preferred |
| `BinaryResponse` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{response_type, tag[4], data}` | Generic wrapper; specific sub-type entries above are preferred |
| `Disabled` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{mc_type: 0x0F, feature_id}` | Bridge returns this to caller when a requested feature is unavailable |
| `Ok` | `—` | — | — | Bridge-synthesized ACK to local caller; Reticulum delivery receipt used for remote |
| `Error` | `direct` | `meshcore.node.<requester_hash>` | `f[FB]`: `{error_code, error_msg}` | Returned when a remote bridge operation fails |
| `Unknown (0xFF)` | `—` | — | — | Discard; log for diagnostics; do not relay |

---

## Transport Distribution Summary

| Transport | Count | Primary Use |
|---|---|---|
| `propagated` | 6 | Text messages (DMs and channels) — needs store-and-forward |
| `direct` | ~40 | Status, telemetry, contact management, diagnostics |
| `announce` | 4 | Node advertisements and discovery |
| `receipt` | 2 | ACK/MsgSent — handled at Reticulum transport layer |
| `—` (internal) | ~48 | Local device config, crypto, admin — must not cross the bridge |
