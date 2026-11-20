/*
 * Main.c
 *
 * Smartcard Demo OS
 *
 * T. Music 05/2023
 *
 */


// These includes may be useless for the demo os,
// but of use for you.
#include <libopencm3/cm3/nvic.h>
#include <libopencm3/stm32/exti.h>
#include <libopencm3/stm32/flash.h>
#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rcc.h>
#include <libopencm3/stm32/usart.h>

#include "sc_system.h"
#include "keys.h"

int main(void) {

    sys_rcc_init();
    // Init the GPIOs so we can config
    // the clock source and ISO7816 reset behavior
    sys_gpio_init();
    sys_set_reset_source(SYSTEM_RSTSRC_ISO7816);
    sys_set_clksource(SYSTEM_CLKSOURCE_CARD_TERMINAL);
    sys_usart_init();

    // RST is active low and wired to the MCU reset through the board's
    // reset gate. Execution resumes here after the reader releases RST.
    // Wait at least 400 reader-clock cycles before starting the ATR.
    for (volatile uint32_t i = 0; i < 400; ++i) {
        __asm__ volatile ("nop");
    }
    sys_usart_send_atr();
    gpio_clear(PORT_LED_G, PIN_LED_G);

    // Each subsequent reader reset restarts main and sends another ATR.
    // APDU command processing belongs to the next challenge.
    while (1) {
        __asm__ volatile ("nop");
    }

    // Never reached
    return 0;
}
