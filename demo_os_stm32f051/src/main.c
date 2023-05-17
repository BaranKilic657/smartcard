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

int main(void) {

    sys_rcc_init();
    // Init the GPIOs so we can config
    // the clock source and ISO7816 reset behavior
    sys_gpio_init();
    sys_set_clksource(SYSTEM_CLKSOURCE_EXT_8MHZ);
    sys_set_reset_source(SYSTEM_RSTSRC_DBG_ONLY);

     while(1) {
        gpio_clear(PORT_LED_R, PIN_LED_R);
        delay_cyc(1000000);
        gpio_set(PORT_LED_R, PIN_LED_R);
        gpio_clear(PORT_LED_G, PIN_LED_G);
        delay_cyc(1000000);
        gpio_set(PORT_LED_G, PIN_LED_G);
        gpio_clear(PORT_LED_B, PIN_LED_B);
        delay_cyc(1000000);
        gpio_set(PORT_LED_B, PIN_LED_B);
    }

    // Never reached
    return 0;
}
