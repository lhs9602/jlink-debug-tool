#ifndef __tdc_debug_jlink_notify_h__
#define __tdc_debug_jlink_notify_h__

/* J-Link 디버그 블록의 CM3 쪽 (DCRDR 알림).
 * CFX tdc_debug_jlink.h 의 같은 이름 스위치와 같은 값으로 둔다. 0 이면 코드가 생성되지 않는다 */
#define TDC_DEBUG_JLINK_ENABLE 1

#if TDC_DEBUG_JLINK_ENABLE
void tdc_debug_jlink_notify_init(void);
#endif

#endif  // __tdc_debug_jlink_notify_h__
