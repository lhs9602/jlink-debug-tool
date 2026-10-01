/**
 * @file tdc_debug_jlink_notify.c
 * @brief J-Link 디버그 블록의 CM3 쪽. CFX 가 CM3_CMD_3 을 보내면 DCRDR 값을 바꿔 PC 에 알린다.
 *        (driver_timmer.c 에 있던 코드를 옮겼다. 동작은 같다)
 */

#include <ci_timer.h>
#include <stdint.h>
#include "tdc_debug_jlink_notify.h"

#if TDC_DEBUG_JLINK_ENABLE

static volatile uint32_t g_tdc_debug_jlink_notify_seq = 0;

/* CFX 가 디버그 블록의 flag 를 바꿀 때마다 온다 (CFX TDC_DEBUG_JLINK_NOTIFY, D_CM3->CMDS = CM3_CMD_3).
 * DCRDR 값을 바꿔 PC 에 알린다. PC 는 값이 바뀌면 켜 둔 블록의 flag 를 읽는다.
 * 0 은 부팅 때 tdc_debug_jlink_notify_init 이 쓰는 값으로만 남긴다. 0xFFFFFFFF 다음은 1 로 넘긴다 */
void CFX_3_IRQHandler(void)
{
    uint32_t seq = g_tdc_debug_jlink_notify_seq + 1u;

    if (seq == 0u)
    {
        seq = 1u;
    }
    g_tdc_debug_jlink_notify_seq = seq;
    CoreDebug->DCRDR             = seq;
}

void tdc_debug_jlink_notify_init(void)
{
    NVIC_DisableIRQ(CFX_3_IRQn);
    g_tdc_debug_jlink_notify_seq = 0;
    CoreDebug->DCRDR             = 0; /* 리셋값이 정해져 있지 않다 */
    NVIC_ClearPendingIRQ(CFX_3_IRQn);
    NVIC_SetPriority(CFX_3_IRQn, 0);
    NVIC_EnableIRQ(CFX_3_IRQn);
}

#endif  // TDC_DEBUG_JLINK_ENABLE
