// ps5bridge: a small C API over chiaki-ng's libchiaki for the ps5-remote
// Python server (ctypes). One bridge handle = one Remote Play session.
// libchiaki is AGPL-3.0 (chiaki-ng v1.10.0, vendored source).

#include <chiaki/session.h>
#include <chiaki/controller.h>
#include <chiaki/log.h>
#include <chiaki/regist.h>

#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define EXPORT __declspec(dllexport)

typedef int (*Ps5VideoCb)(const uint8_t *buf, size_t size, int32_t frames_lost, int recovered, void *user);
typedef void (*Ps5EventCb)(int type, int code, const char *text, void *user);
typedef void (*Ps5LogCb)(int level, const char *msg, void *user);

typedef struct {
	ChiakiSession session;
	ChiakiLog log;
	ChiakiControllerState state;
	ChiakiMutex state_mutex;
	char host[256];
	Ps5VideoCb video_cb;
	Ps5EventCb event_cb;
	Ps5LogCb log_cb;
	void *user;
	int started;
} Ps5Bridge;

// Event types passed to Python. Values match ChiakiEventType where one exists.
enum {
	PS5_EVENT_CONNECTED = 0,
	PS5_EVENT_LOGIN_PIN_REQUEST = 1,
	PS5_EVENT_KEYBOARD_OPEN = 5,
	PS5_EVENT_KEYBOARD_TEXT_CHANGE = 6,
	PS5_EVENT_KEYBOARD_REMOTE_CLOSE = 7,
	PS5_EVENT_RUMBLE = 8,
	PS5_EVENT_QUIT = 9,
	PS5_EVENT_VIDEO_FEC_FAILURE = 16,
	PS5_EVENT_CANT_DISPLAY = 100, // code 1: the PS5 is blanking the stream (protected content)
};

static void bridge_log_cb(ChiakiLogLevel level, const char *msg, void *user)
{
	Ps5Bridge *b = user;
	if(b && b->log_cb)
		b->log_cb((int)level, msg, b->user);
}

static void bridge_event_cb(ChiakiEvent *event, void *user)
{
	Ps5Bridge *b = user;
	if(!b->event_cb)
		return;
	switch(event->type)
	{
		case CHIAKI_EVENT_CONNECTED:
			b->event_cb(PS5_EVENT_CONNECTED, 0, NULL, b->user);
			break;
		case CHIAKI_EVENT_LOGIN_PIN_REQUEST:
			b->event_cb(PS5_EVENT_LOGIN_PIN_REQUEST, event->login_pin_request.pin_incorrect, NULL, b->user);
			break;
		case CHIAKI_EVENT_KEYBOARD_OPEN:
			b->event_cb(PS5_EVENT_KEYBOARD_OPEN, 0, event->keyboard.text_str, b->user);
			break;
		case CHIAKI_EVENT_KEYBOARD_TEXT_CHANGE:
			b->event_cb(PS5_EVENT_KEYBOARD_TEXT_CHANGE, 0, event->keyboard.text_str, b->user);
			break;
		case CHIAKI_EVENT_KEYBOARD_REMOTE_CLOSE:
			b->event_cb(PS5_EVENT_KEYBOARD_REMOTE_CLOSE, 0, NULL, b->user);
			break;
		case CHIAKI_EVENT_RUMBLE:
			b->event_cb(PS5_EVENT_RUMBLE, (event->rumble.left << 8) | event->rumble.right, NULL, b->user);
			break;
		case CHIAKI_EVENT_QUIT:
		{
			char msg[512];
			snprintf(msg, sizeof(msg), "%s%s%s",
				chiaki_quit_reason_string(event->quit.reason),
				event->quit.reason_str ? ": " : "",
				event->quit.reason_str ? event->quit.reason_str : "");
			b->event_cb(PS5_EVENT_QUIT, (int)event->quit.reason, msg, b->user);
			break;
		}
		case CHIAKI_EVENT_VIDEO_FEC_FAILURE:
			b->event_cb(PS5_EVENT_VIDEO_FEC_FAILURE, event->video_fec_failure.frame_index, NULL, b->user);
			break;
		default:
			break;
	}
}

// libchiaki calls these sinks without NULL checks, so every session needs them.
static void bridge_cantdisplay_cb(void *user, bool cant_display)
{
	Ps5Bridge *b = user;
	if(b->event_cb)
		b->event_cb(PS5_EVENT_CANT_DISPLAY, cant_display ? 1 : 0, NULL, b->user);
}

static void bridge_audio_header_cb(ChiakiAudioHeader *header, void *user)
{
	(void)header; (void)user;
}

static void bridge_audio_frame_cb(uint8_t *buf, size_t buf_size, void *user)
{
	(void)buf; (void)buf_size; (void)user;
}

static bool bridge_video_cb(uint8_t *buf, size_t buf_size, int32_t frames_lost, bool frame_recovered, void *user)
{
	Ps5Bridge *b = user;
	if(!b->video_cb)
		return true;
	return b->video_cb(buf, buf_size, frames_lost, frame_recovered ? 1 : 0, b->user) != 0;
}

EXPORT int ps5_lib_init(void)
{
	return (int)chiaki_lib_init();
}

EXPORT const char *ps5_error_string(int err)
{
	return chiaki_error_string((ChiakiErrorCode)err);
}

// regist_key: 16 bytes (ASCII of the PS5-RegistKey hex, zero padded).
// morning: 16 bytes (RP-Key). account_id: 8 bytes (PSN account ID, little endian).
// resolution: 1=360p 2=540p 3=720p 4=1080p. fps: 30 or 60. bitrate_kbps: 0 = preset.
EXPORT Ps5Bridge *ps5_start(
	const char *host, const uint8_t *regist_key, const uint8_t *morning, const uint8_t *account_id,
	int is_ps5, int resolution, int fps, int bitrate_kbps, int disable_audio,
	Ps5VideoCb video_cb, Ps5EventCb event_cb, Ps5LogCb log_cb, int log_mask, void *user, int *err_out)
{
	Ps5Bridge *b = calloc(1, sizeof(Ps5Bridge));
	if(!b)
	{
		if(err_out) *err_out = CHIAKI_ERR_MEMORY;
		return NULL;
	}
	b->video_cb = video_cb;
	b->event_cb = event_cb;
	b->log_cb = log_cb;
	b->user = user;
	strncpy(b->host, host, sizeof(b->host) - 1);
	chiaki_log_init(&b->log, (uint32_t)log_mask, bridge_log_cb, b);
	chiaki_controller_state_set_idle(&b->state);
	chiaki_mutex_init(&b->state_mutex, false);

	ChiakiConnectInfo info;
	memset(&info, 0, sizeof(info));
	info.ps5 = is_ps5 != 0;
	info.host = b->host;
	memcpy(info.regist_key, regist_key, sizeof(info.regist_key));
	memcpy(info.morning, morning, sizeof(info.morning));
	memcpy(info.psn_account_id, account_id, sizeof(info.psn_account_id));
	chiaki_connect_video_profile_preset(&info.video_profile,
		(ChiakiVideoResolutionPreset)resolution,
		fps >= 60 ? CHIAKI_VIDEO_FPS_PRESET_60 : CHIAKI_VIDEO_FPS_PRESET_30);
	if(bitrate_kbps > 0)
		info.video_profile.bitrate = (unsigned int)bitrate_kbps;
	info.video_profile.codec = CHIAKI_CODEC_H264;
	info.video_profile_auto_downgrade = true;
	info.enable_keyboard = true;
	info.enable_dualsense = false;
	info.audio_video_disabled = disable_audio ? CHIAKI_AUDIO_DISABLED : CHIAKI_NONE_DISABLED;
	info.auto_regist = false;
	info.holepunch_session = NULL;
	info.rudp_sock = NULL;
	info.packet_loss_max = 0.05;
	info.enable_idr_on_fec_failure = true;

	ChiakiErrorCode err = chiaki_session_init(&b->session, &info, &b->log);
	if(err != CHIAKI_ERR_SUCCESS)
	{
		if(err_out) *err_out = err;
		chiaki_mutex_fini(&b->state_mutex);
		free(b);
		return NULL;
	}
	chiaki_session_set_event_cb(&b->session, bridge_event_cb, b);
	chiaki_session_set_video_sample_cb(&b->session, bridge_video_cb, b);
	ChiakiCtrlDisplaySink display_sink = { .user = b, .cantdisplay_cb = bridge_cantdisplay_cb };
	chiaki_session_ctrl_set_display_sink(&b->session, &display_sink);
	ChiakiAudioSink audio_sink = { .user = b, .header_cb = bridge_audio_header_cb, .frame_cb = bridge_audio_frame_cb };
	chiaki_session_set_audio_sink(&b->session, &audio_sink);
	chiaki_session_set_haptics_sink(&b->session, &audio_sink);

	err = chiaki_session_start(&b->session);
	if(err != CHIAKI_ERR_SUCCESS)
	{
		if(err_out) *err_out = err;
		chiaki_session_fini(&b->session);
		chiaki_mutex_fini(&b->state_mutex);
		free(b);
		return NULL;
	}
	b->started = 1;
	if(err_out) *err_out = 0;
	return b;
}

EXPORT int ps5_set_controller(Ps5Bridge *b, uint32_t buttons, uint8_t l2, uint8_t r2,
	int16_t lx, int16_t ly, int16_t rx, int16_t ry)
{
	if(!b) return CHIAKI_ERR_INVALID_DATA;
	chiaki_mutex_lock(&b->state_mutex);
	b->state.buttons = buttons;
	b->state.l2_state = l2;
	b->state.r2_state = r2;
	b->state.left_x = lx;
	b->state.left_y = ly;
	b->state.right_x = rx;
	b->state.right_y = ry;
	ChiakiControllerState copy = b->state;
	chiaki_mutex_unlock(&b->state_mutex);
	return (int)chiaki_session_set_controller_state(&b->session, &copy);
}

EXPORT int ps5_keyboard_set_text(Ps5Bridge *b, const char *text)
{
	return b ? (int)chiaki_session_keyboard_set_text(&b->session, text) : CHIAKI_ERR_INVALID_DATA;
}

EXPORT int ps5_keyboard_accept(Ps5Bridge *b)
{
	return b ? (int)chiaki_session_keyboard_accept(&b->session) : CHIAKI_ERR_INVALID_DATA;
}

EXPORT int ps5_keyboard_reject(Ps5Bridge *b)
{
	return b ? (int)chiaki_session_keyboard_reject(&b->session) : CHIAKI_ERR_INVALID_DATA;
}

EXPORT int ps5_go_home(Ps5Bridge *b)
{
	return b ? (int)chiaki_session_go_home(&b->session) : CHIAKI_ERR_INVALID_DATA;
}

EXPORT int ps5_goto_bed(Ps5Bridge *b)
{
	return b ? (int)chiaki_session_goto_bed(&b->session) : CHIAKI_ERR_INVALID_DATA;
}

EXPORT int ps5_set_login_pin(Ps5Bridge *b, const char *pin)
{
	return b ? (int)chiaki_session_set_login_pin(&b->session, (const uint8_t *)pin, strlen(pin)) : CHIAKI_ERR_INVALID_DATA;
}

// ---------- one-time link (Remote Play registration) ----------

typedef struct {
	ChiakiMutex mutex;
	ChiakiCond cond;
	int done;
	int ok;
	ChiakiRegisteredHost host;
	Ps5LogCb log_cb;
	void *user;
} RegistWait;

static void regist_log_cb(ChiakiLogLevel level, const char *msg, void *user)
{
	RegistWait *w = user;
	if(w->log_cb)
		w->log_cb((int)level, msg, w->user);
}

static void regist_cb(ChiakiRegistEvent *event, void *user)
{
	RegistWait *w = user;
	chiaki_mutex_lock(&w->mutex);
	w->done = 1;
	w->ok = event->type == CHIAKI_REGIST_EVENT_TYPE_FINISHED_SUCCESS;
	if(w->ok && event->registered_host)
		w->host = *event->registered_host;
	chiaki_mutex_unlock(&w->mutex);
	chiaki_cond_signal(&w->cond);
}

static bool regist_done(void *user)
{
	return ((RegistWait *)user)->done != 0;
}

// Links this client to a PS5 using the PIN from Settings > System > Remote Play >
// Link Device. Blocks up to timeout_ms. Returns 0 on success and fills:
// regist_key_out (16 bytes), rp_key_out (16), nickname_out (32, NUL terminated), mac_out (6).
EXPORT int ps5_register(const char *host, const uint8_t *account_id, uint32_t pin, int timeout_ms,
	uint8_t *regist_key_out, uint8_t *rp_key_out, char *nickname_out, uint8_t *mac_out,
	Ps5LogCb log_cb, int log_mask, void *user)
{
	RegistWait w;
	memset(&w, 0, sizeof(w));
	w.log_cb = log_cb;
	w.user = user;
	chiaki_mutex_init(&w.mutex, false);
	chiaki_cond_init(&w.cond);

	ChiakiLog log;
	chiaki_log_init(&log, (uint32_t)log_mask, regist_log_cb, &w);

	ChiakiRegistInfo info;
	memset(&info, 0, sizeof(info));
	info.target = CHIAKI_TARGET_PS5_1;
	info.host = host;
	info.broadcast = false;
	info.psn_online_id = NULL;
	memcpy(info.psn_account_id, account_id, CHIAKI_PSN_ACCOUNT_ID_SIZE);
	info.pin = pin;
	info.console_pin = 0;
	info.holepunch_info = NULL;
	info.rudp = NULL;

	ChiakiRegist regist;
	ChiakiErrorCode err = chiaki_regist_start(&regist, &log, &info, regist_cb, &w);
	if(err != CHIAKI_ERR_SUCCESS)
	{
		chiaki_cond_fini(&w.cond);
		chiaki_mutex_fini(&w.mutex);
		return (int)err;
	}
	chiaki_mutex_lock(&w.mutex);
	err = chiaki_cond_timedwait_pred(&w.cond, &w.mutex, (uint64_t)timeout_ms, regist_done, &w);
	int done = w.done, ok = w.ok;
	chiaki_mutex_unlock(&w.mutex);
	if(!done)
		chiaki_regist_stop(&regist);
	chiaki_regist_fini(&regist);

	int result = CHIAKI_ERR_UNKNOWN;
	if(!done)
		result = CHIAKI_ERR_TIMEOUT;
	else if(ok)
	{
		memcpy(regist_key_out, w.host.rp_regist_key, sizeof(w.host.rp_regist_key));
		memcpy(rp_key_out, w.host.rp_key, sizeof(w.host.rp_key));
		memset(nickname_out, 0, 32);
		strncpy(nickname_out, w.host.server_nickname, 31);
		memcpy(mac_out, w.host.server_mac, 6);
		result = 0;
	}
	chiaki_cond_fini(&w.cond);
	chiaki_mutex_fini(&w.mutex);
	return result;
}

// Stops the session and frees the handle. Blocks until the session thread exits.
EXPORT void ps5_stop(Ps5Bridge *b)
{
	if(!b) return;
	if(b->started)
	{
		chiaki_session_stop(&b->session);
		chiaki_session_join(&b->session);
	}
	chiaki_session_fini(&b->session);
	chiaki_mutex_fini(&b->state_mutex);
	free(b);
}
