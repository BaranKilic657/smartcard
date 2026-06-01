
#include "keys.h"

#define KEYRAM __attribute__((section(".app_keys")))
#define KEYRAM_AES_KEY __attribute__((section(".app_keys.aes_key")))


// Set your application AES key here. This key will be used when you program the card
// using the debugger. Compiling as app and flashing to the reference card, the web
// portal will select a new key for you.

KEYRAM_AES_KEY
static const uint8_t aes_key[16] = { 50, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1 };

const uint8_t* get_application_aes_key() {
    return aes_key;
}
