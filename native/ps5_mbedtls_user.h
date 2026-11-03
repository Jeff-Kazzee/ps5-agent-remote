/* Mbed TLS 2.28 overrides for ps5bridge.dll.
 * The AES-NI and VIA Padlock inline-assembly paths crash under zig cc
 * (access violation on the first AES use in libchiaki ctrl, 2026-11-02).
 * The portable C AES is fast enough for Remote Play control traffic. */
#undef MBEDTLS_AESNI_C
#undef MBEDTLS_PADLOCK_C
