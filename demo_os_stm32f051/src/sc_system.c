/*
 * sc_system.c
 *
 * Smartcard Demo OS
 *
 * T. Music 05/2023
 *
 */

#include <stddef.h>

#include <libopencm3/stm32/flash.h>
#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rcc.h>
#include <libopencm3/stm32/usart.h>
#include <libopencm3/cm3/systick.h>

#include "sc_system.h"

/*
    Function sys_gpio_init()

    Configures all GPIOs on the card and puts them into a predefined state

*/
void sys_gpio_init() {
    // Enable the GPIO periphal clocks
    rcc_periph_clock_enable(RCC_GPIOA);
    rcc_periph_clock_enable(RCC_GPIOB);

    // Configure the LEDs
    // Set the GPIOs (LEDs are inverted)
    // Red and green led share a GPIO port
    gpio_set(PORT_LED_R, PIN_LED_R | PIN_LED_G); 
    // Blue has its own GPIO port
    gpio_set(PORT_LED_B, PIN_LED_B);
    gpio_mode_setup(PORT_LED_R, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, PIN_LED_R | PIN_LED_G);
    gpio_set_output_options(PORT_LED_R, GPIO_OTYPE_OD, GPIO_OSPEED_2MHZ, PIN_LED_R | PIN_LED_G);
    gpio_mode_setup(PORT_LED_B, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, PIN_LED_B);
    gpio_set_output_options(PORT_LED_B, GPIO_OTYPE_OD, GPIO_OSPEED_2MHZ, PIN_LED_B);

    // 7816 Reset Disable Pin
    // By default this pin is strapped low on the pcb. Thus, if a card reader wants to
    // perform a reset, the STM32 will reset, too. In case you are debugging, you might not
    // want your card to be reset everytime the reader sees a timeout.
    gpio_clear(PORT_ISO7816_RST_DIS, PIN_ISO7816_RST_DIS);
    gpio_mode_setup(PORT_ISO7816_RST_DIS, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, PIN_ISO7816_RST_DIS);
    gpio_set_output_options(PORT_ISO7816_RST_DIS, GPIO_OTYPE_PP, GPIO_OSPEED_2MHZ, PIN_ISO7816_RST_DIS);

    // Clock Source Select Pin CLKSEL
    // When low, the STM32 receives the card reader clock on its HSE pin
    // This means, when selecting HSE as clock source, the controller runs with the wonky reader clock
    // this may be favorable for transmitting the ATR and further communication, but unfavorable for
    // performing measurements. Thus, this signal is high by default.
    gpio_set(PORT_CLKSEL, PIN_CLKSEL);
    gpio_mode_setup(PORT_CLKSEL, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, PIN_CLKSEL);
    gpio_set_output_options(PORT_CLKSEL, GPIO_OTYPE_PP, GPIO_OSPEED_2MHZ, PIN_CLKSEL);

    // Trigger Pin
    gpio_clear(PORT_TRIGGER, PIN_TRIGGER);
    gpio_mode_setup(PORT_TRIGGER, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, PIN_TRIGGER);
    gpio_set_output_options(PORT_TRIGGER, GPIO_OTYPE_PP, GPIO_OSPEED_100MHZ, PIN_TRIGGER);

}

void sys_set_reset_source(uint8_t src) {
    if (src != SYSTEM_RSTSRC_ISO7816 && src != SYSTEM_RSTSRC_DBG_ONLY) {
        // Invalid source has been selected -> exit
        return;
    }

    if (src == SYSTEM_RSTSRC_ISO7816)
        gpio_clear(PORT_ISO7816_RST_DIS, PIN_ISO7816_RST_DIS);
    else
        gpio_set(PORT_ISO7816_RST_DIS, PIN_ISO7816_RST_DIS);

    return;
}

void sys_rcc_init() {
    // Some general settings for the clock configuration

    // Also the card will never have clock speeds > 8 MHz, so keep the
    // flash wait states at zero
    flash_set_ws(FLASH_ACR_LATENCY_0WS);

    // At this time we are running from the HSI, so 8 MHz
    rcc_ahb_frequency  = 8000000;
    rcc_apb1_frequency = 8000000;
    rcc_apb2_frequency = 8000000;
}

// Set the desired clock source for the system.
// Changing the system clock requires adjusting divider
// settings throughout the system for peripherals like USART
void sys_set_clksource(uint8_t src) {
    if (src != SYSTEM_CLKSOURCE_CARD_TERMINAL && src != SYSTEM_CLKSOURCE_EXT_8MHZ) {
        // Invalid source has been selected -> exit
        return;
    }

    // As both clock options are being received through the HSE pin,
    // hop on the internal oscillator for the time between changing
    rcc_osc_on(RCC_HSI);
    rcc_wait_for_osc_ready(RCC_HSI);
    rcc_set_sysclk_source(RCC_HSI);

    rcc_osc_off(RCC_HSE);
    // Bypass the oscillator -> we are supplied by a stable clock
    RCC_CR |= RCC_CR_HSEBYP;

    // The desired clock source is the card terminal
    if (src == SYSTEM_CLKSOURCE_CARD_TERMINAL) {
        // Set CLKSEL pin low to disable the pcb oscillator
        // and pass through the card terminal clock
        gpio_clear(PORT_CLKSEL, PIN_CLKSEL);
    } else {
        gpio_set(PORT_CLKSEL, PIN_CLKSEL);
    }

    // Re-enable the HSE
    rcc_osc_on(RCC_HSE);
    rcc_wait_for_osc_ready(RCC_HSE);
    rcc_set_sysclk_source(RCC_HSE);

    // Turn off the HSI
    rcc_osc_off(RCC_HSI);

    return;
}

void sys_usart_init() {
    /*
        Note:
        Not using so many functions of the libopencm3 as, e.g., the usart
        functions for modesetting do only utilize USART_CR1, whereas some mode
        settings we need are in USART_CR3. To avoid any misdirections during
        config, write to the regs directly. Libopencm3 functions only utillized
        for very basics like baudrate and stoppbits.
    */

    rcc_periph_clock_enable(RCC_GPIOA);
    rcc_periph_clock_enable(RCC_USART1);

    // PA9 / AF1 is USART1_TX on the STM32F051. The shared ISO7816
    // I/O line must be released high, never driven high push-pull.
    gpio_mode_setup(PORT_USART1_TX, GPIO_MODE_AF, GPIO_PUPD_NONE, PIN_USART1_TX);
    gpio_set_output_options(PORT_USART1_TX, GPIO_OTYPE_OD,
                            GPIO_OSPEED_2MHZ, PIN_USART1_TX);
    gpio_set_af(PORT_USART1_TX, GPIO_AF1, PIN_USART1_TX);

    usart_disable(USART1);
    USART_CR1(USART1) = USART_CR1_M | USART_CR1_PCE | USART_CR1_TE;
    USART_CR2(USART1) = 0;
    USART_CR3(USART1) = USART_CR3_SCEN;
    usart_set_stopbits(USART1, USART_STOPBITS_1_5);

    // SYSCLK and USART1 use the reader clock directly. Set the divider
    // rather than assuming that the reader supplies exactly 8 MHz:
    // one ETU = 372 reader clock cycles (ATR default Fi=372, Di=1).
    USART_BRR(USART1) = 372;
    // Two extra baud periods between characters; CK output is unused.
    USART_GTPR(USART1) = (2U << 8);
    usart_enable(USART1);

    return;
}

void sys_usart_send(uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        while (!(USART_ISR(USART1) & USART_ISR_TXE)) {
        }
        USART_ICR(USART1) = USART_ICR_TCCF;
        USART_TDR(USART1) = data[i];
        while (!(USART_ISR(USART1) & USART_ISR_TC)) {
        }
    }
}

void sys_usart_send_atr() {

    // Direct convention, T=0, default interface parameters, no historical
    // bytes. A T=0-only ATR does not include a checksum (TCK).
    uint8_t atr[] = {0x3B, 0x00};
    sys_usart_send(atr, sizeof(atr));
    return;
}

void delay_cyc(uint32_t cycles) {
    // The loop translates to roughly two cycles,
    // so just div cycles by two and we good
    cycles = cycles >> 1;
    while (cycles > 0) {
        cycles--;
        __asm__("nop");
    }
}

// Systick Interrupt Handler
void sys_tick_handler(void) {
    static uint8_t i = 0;
    if (i == 0) {
        gpio_clear(PORT_LED_G, PIN_LED_G);
        i++;
    } else {
        i=0;
        gpio_set(PORT_LED_G, PIN_LED_G);
    }
}

// In case you wish to use the systick:
void systick_setup(int xms) {
    /* div8 per ST, stays compatible with M3/M4 parts, well done ST */
    systick_set_clocksource(STK_CSR_CLKSOURCE_EXT);
    /* clear counter so it starts right away */
    STK_CVR = 0;

    systick_set_reload(8000000UL / 8 / 1000 * xms);
    systick_counter_enable();
    systick_interrupt_enable();
}

