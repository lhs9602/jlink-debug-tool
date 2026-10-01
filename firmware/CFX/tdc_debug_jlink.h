/**
 * @file tdc_debug_jlink.h
 * @brief J-Link 디버그 블록. PC 가 J-Link 로 읽고 쓰는 구조체(블록)를 정해진 규약으로 P 메모리에 둔다.
 *        블록: 1 DMIC (기록과 주입), 2 vMag. 코드는 tdc_debug_jlink.c.
 *
 * 영역 모양 (시작 주소 CFX P:0x64000 = CM3 0x21010000, 1 칸 = CFX 1 워드 = CM3 4 바이트)
 *   header   magic, size, 항목 {id, start, size, word_bytes} x 블록 수
 *   블록     table_size, 멤버 표 {offset, count} x 멤버 수, 그 뒤 데이터
 * PC 는 header 로 블록을 찾고, 블록의 멤버 표로 멤버를 찾는다. 규약: jlink-debug-tool 설계_구조체디렉터리.md
 *
 * 블록 더하기
 *   (1) 번호 TDC_DEBUG_JLINK_ID_<이름> 하나 추가 (기존 번호는 바꾸지 않는다), TDC_DEBUG_JLINK_ENTRY_N + 1
 *   (2) 블록 정의. 맨 앞은 table_size 와 table[멤버 수], 그 뒤 데이터. 타입은 int, unsigned int 와 그 배열만
 *      (uint32_t 등은 CFX 에서 칸 수가 달라져 쓰지 않는다)
 *   (3) 영역 tdc_debug_jlink_area_t 의 맨 끝에 추가
 *   (4) tdc_debug_jlink.c 의 tdc_debug_jlink_register() 에 등록 한 줄, 표 크기 한 줄, 멤버마다 한 줄
 * 멤버를 나중에 더할 때는 (2) 에 멤버를 넣고 (4) 의 멤버 줄을 맨 끝에 하나 더한다 (표 순번이 곧 멤버 번호다).
 * PC 쪽 정의는 (4) 의 멤버 줄과 같은 순서, 같은 크기로 적는다. 펌웨어가 기준이다.
 */

#ifndef __tdc_debug_jlink_h__
#define __tdc_debug_jlink_h__

#include <hw.h>
#include <stddef.h> /* offsetof */
#include <definitionsForAlgorithm.h>
#include <microcode.h>

/* 1 이면 디버그 블록 전체(header, DMIC, vMag, CM3 알림)가 빌드된다. 0 이면 코드가 생성되지 않는다.
 * CM3 tdc_debug_jlink_notify.h 의 같은 이름 스위치와 같은 값으로 둔다 */
#define TDC_DEBUG_JLINK_ENABLE 1

/* 영역 시작 주소. 옮길 때는 이 한 줄과 PC 쪽 ini 의 header 주소를 함께 고친다.
 * 옮길 곳은 P 메모리 중 링커가 쓰지 않는 곳이어야 한다 (지금 자리는 app_LCF.bcf 가 _reserved 로 막은 ARAM) */
#define TDC_DEBUG_JLINK_BASE   D_DSP_ARAM23_BASE

/* header 맨 앞 값. PC 는 이 값이 있어야 디버그 블록이 있다고 본다 (24 비트 안, 바꾸지 않는다) */
#define TDC_DEBUG_JLINK_MAGIC  0x7DC001

/* CFX 블록의 한 칸이 CM3 에서 몇 바이트인가 */
#define TDC_DEBUG_JLINK_CFX_WORD_BYTES 4

/* (1) 블록 번호 */
#define TDC_DEBUG_JLINK_ID_DMIC   1
#define TDC_DEBUG_JLINK_ID_VMAG   2 /* 2026-09-30 주입을 DMIC 에 합치며 3 -> 2 (배포 전이라 당겼다) */

/* 영역에 넣은 블록 수 (등록 줄 TDC_DEBUG_JLINK_ENTRY 의 수) */
#define TDC_DEBUG_JLINK_ENTRY_N 2

/* 블록 크기 */
#define TDC_DEBUG_JLINK_DMIC_LEN          512 /* DMIC 버퍼 하나의 샘플 수 (32 ms). 기록과 주입이 같이 쓴다 */
#define TDC_DEBUG_JLINK_VMAG_BANDS        df_MaxNumOfElectrode             /* 1 ms 에 쓰는 밴드 대표값 수 (32) */
#define TDC_DEBUG_JLINK_VMAG_LEN          (16 * TDC_DEBUG_JLINK_VMAG_BANDS) /* vMag 버퍼 하나 = 16 프레임 (512 칸, 16 ms) */

/* 멤버 표 항목. offset = 블록 시작(table_size 칸)에서 몇 칸 뒤, count = 칸 수 */
typedef struct
{
    unsigned int offset;
    unsigned int count;
} tdc_debug_jlink_member_t;

/* header 항목. start = 영역 시작에서 몇 칸 뒤, size = 블록 칸 수 */
typedef struct
{
    unsigned int id;
    unsigned int start;
    unsigned int size;
    unsigned int word_bytes;
} tdc_debug_jlink_entry_t;

/* header (블록 목록). 영역 맨 앞에 둔다 */
typedef struct
{
    unsigned int            magic;
    unsigned int            size; /* header 칸 수 */
    tdc_debug_jlink_entry_t entry[TDC_DEBUG_JLINK_ENTRY_N];
} tdc_debug_jlink_header_t;

/* (2) DMIC (번호 1). 더블 버퍼 핸드셰이크.
 * PC 가 쓰는 동안 (dmic_enable 1) 만 main.c 가 tdc_debug_jlink_dmic() 을 부른다. 0 이면 부르지 않는다.
 * 함수 안에서 dmic_inj_enable 로 방향을 고른다 (0 기록, 1 주입)
 * 기록 (dmic_inj_enable 0)
 * - 1 ms 마다 입력 FIFO 16 샘플을 dmic_buf[dmic_cur_buf][dmic_pos] 부터 이어 쓴다.
 * - 512 가 차면 그 버퍼의 dmic_buf_full 을 1 로 두고 다른 버퍼로 옮겨 이어 쓰며 CM3 에 알린다.
 * - 두 버퍼가 모두 차 있으면 쓰지 않고 dmic_missing_cnt 를 1 늘린다 (1 = 1 ms = 16 샘플).
 * - PC 는 dmic_buf_full 이 1 인 버퍼만 읽고 0 을 쓴다. 두 버퍼가 다 찼으면 dmic_cur_buf 쪽이 먼저 찬 버퍼다.
 * - 16 샘플은 FIFO 인덱스 0 -> 15 순서로 복사한다 (FIFO 인덱스 0 이 가장 최근 샘플).
 * 주입 (dmic_inj_enable 1). 방향만 반대다
 * - PC 가 dmic_buf_full 이 0 인 버퍼에 512 샘플(시간 순서, 입력 FIFO 단위)을 채우고 1 을 쓴다.
 * - CFX 는 1 ms 마다 dmic_buf[dmic_cur_buf][dmic_pos] 부터 16 샘플을 꺼내 FIFO 순서로 뒤집어 믹서 결과 대신 쓴다.
 *   마이크에 입력 LPF (2-tap 이동평균) 가 걸리는 1 ms 에는 주입 샘플에도 같은 식으로 건다.
 * - 512 를 다 꺼내면 그 버퍼의 dmic_buf_full 을 0 으로 두고 다른 버퍼로 옮기며 CM3 에 알린다.
 * - 꺼낼 버퍼가 비어 있으면 그 1 ms 는 무음, dmic_missing_cnt 를 1 늘리고 그 자리에서 기다린다.
 * - PC 시작 순서: dmic_inj_enable 0 -> dmic_buf_full 1, 1 (기록 멈춤) -> 2 ms 기다림 -> 두 버퍼 채움
 *   -> dmic_pos 0, dmic_cur_buf 0 -> dmic_inj_enable 1 -> dmic_missing_cnt 0.
 * - PC 끄기 순서: dmic_buf_full 1, 1 -> dmic_inj_enable 0 -> 2 ms 기다림 -> dmic_pos 0, dmic_cur_buf 0
 *   -> dmic_buf_full 0, 0 (기록을 버퍼 0 처음부터 다시) -> dmic_missing_cnt 0.
 * 켜기 (PC): dmic_enable 0 -> 2 ms 기다림 -> dmic_buf_full 0, 0, dmic_pos 0, dmic_cur_buf 0, dmic_missing_cnt 0 -> dmic_enable 1.
 * 끄기 (PC): dmic_enable 0. 초기화는 PC 가 한다 (펌웨어 초기값은 모두 0 = 꺼짐).
 * 멤버는 맨 끝에 더했다: dmic_inj_enable 순번 6, dmic_enable 순번 7. 순번 0 ~ 5 는 주입을 합치기 전과 같다. */
typedef struct
{
    unsigned int             table_size;
    tdc_debug_jlink_member_t table[8];
    int                      dmic_buf_full[2];                          /* 0  1 = 데이터가 있다 (기록: CFX 가 1, PC 가 0 / 주입: PC 가 1, CFX 가 0) */
    int                      dmic_pos;                                  /* 1  지금 버퍼 안의 다음 위치 (0 ~ 511) */
    int                      dmic_cur_buf;                              /* 2  CFX 가 지금 쓰거나 꺼내는 버퍼 (0 / 1) */
    unsigned int             dmic_missing_cnt;                          /* 3  PC 가 늦어 버퍼가 준비되지 않은 1 ms 횟수 (기록: 쓰지 못함, 주입: 무음) */
    int                      dmic_buf[2][TDC_DEBUG_JLINK_DMIC_LEN];     /* 4 = dmic_buf[0], 5 = dmic_buf[1] */
    int                      dmic_inj_enable;                           /* 6  PC: 1 주입, 0 기록 */
    int                      dmic_enable;                               /* 7  PC: 1 사용, 0 사용 안 함 (0 이면 main.c 가 DMIC 함수를 부르지 않는다) */
} tdc_debug_jlink_dmic_t;

/* (2) vMag (번호 2). DMIC 기록과 같은 더블 버퍼
 * - PC 가 쓰는 동안 (vmag_enable 1) 만 main.c 가 tdc_debug_jlink_vmag_capture() 를 부른다. 0 이면 부르지 않는다.
 * - 1 ms 마다 밴드 대표값 32 개(g_freq_rep_values, 대표값 계산 뒤)를 이어 쓴다. 버퍼 하나 = 16 프레임.
 * - LiveStimulation 모드에서만 쓴다 (그 모드에서만 대표값을 계산한다).
 * - 켜기 (PC): vmag_enable 0 -> 2 ms 기다림 -> vmag_buf_full 0, 0, vmag_write_pos 0, vmag_write_buf 0, vmag_missing_cnt 0 -> vmag_enable 1.
 *   끄기 (PC): vmag_enable 0. */
typedef struct
{
    unsigned int             table_size;
    tdc_debug_jlink_member_t table[7];
    int                      vmag_buf_full[2];                          /* 0  CFX 가 1 (버퍼가 찼다), PC 가 0 */
    int                      vmag_write_pos;                            /* 1  지금 쓰는 버퍼 안의 다음 쓰기 위치 (0 ~ 511) */
    int                      vmag_write_buf;                            /* 2  지금 쓰는 버퍼 (0 / 1) */
    unsigned int             vmag_missing_cnt;                          /* 3  두 버퍼가 다 차서 기록하지 못한 1 ms 횟수 */
    int                      vmag_buf[2][TDC_DEBUG_JLINK_VMAG_LEN];     /* 4 = vmag_buf[0], 5 = vmag_buf[1]. 16 프레임 x 32 밴드 */
    int                      vmag_enable;                               /* 6  PC: 1 사용, 0 사용 안 함 (0 이면 main.c 가 vMag 함수를 부르지 않는다) */
} tdc_debug_jlink_vmag_t;

/* (3) 영역. 적은 순서가 곧 메모리 순서다. 새 블록은 맨 끝에 적는다.
 *
 *   시작 주소 (CFX P:0x64000 = CM3 0x21010000)
 *   +------------------------+
 *   | header  (블록 목록)     |  <- PC 가 연결 때 한 번 읽는다
 *   +------------------------+
 *   | dmic    (번호 1)        |
 *   +------------------------+
 *   | vmag    (번호 2)        |
 *   +------------------------+
 *   | (새 블록은 여기)        |
 */
typedef struct
{
    tdc_debug_jlink_header_t header; /* 맨 앞 */
    tdc_debug_jlink_dmic_t   dmic;
    tdc_debug_jlink_vmag_t   vmag;
} tdc_debug_jlink_area_t;

/* 견본: 따라 만드는 예시 블록 (번호 99, 실제 영역에는 넣지 않는다)
 *
 *   (1)  #define TDC_DEBUG_JLINK_ID_EXAMPLE 99        TDC_DEBUG_JLINK_ENTRY_N 은 1 늘린다
 *   (2)  typedef struct
 *        {
 *            unsigned int             table_size;
 *            tdc_debug_jlink_member_t table[2];
 *            int                      ex_value;        0
 *            int                      ex_samples[16];  1
 *        } tdc_debug_jlink_example_t;
 *   (3)  tdc_debug_jlink_area_t 맨 끝에   tdc_debug_jlink_example_t example;
 *   (4)  tdc_debug_jlink_register() 에
 *        TDC_DEBUG_JLINK_ENTRY(2, TDC_DEBUG_JLINK_ID_EXAMPLE, example);
 *        TDC_DEBUG_JLINK_TABLE(example);
 *        TDC_DEBUG_JLINK_MEMBER(example, 0, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_example_t, ex_value),   1);
 *        TDC_DEBUG_JLINK_MEMBER(example, 1, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_example_t, ex_samples), 16);
 */

/* 영역 포인터 */
#define TDC_DEBUG_JLINK_AREA ((volatile tdc_debug_jlink_area_t chess_storage(IOMEM) *) TDC_DEBUG_JLINK_BASE)

/* 칸 계산. 멤버 타입이 int, unsigned int 와 그 배열뿐이라 CFX 에서 offsetof, sizeof 가 곧 칸 수다 */
#define TDC_DEBUG_JLINK_WOFF(type, m)   ((unsigned int) offsetof(type, m))
#define TDC_DEBUG_JLINK_WSIZE(type, m)  ((unsigned int) sizeof(((type *) 0)->m))

/* 등록 (tdc_debug_jlink_register 안에서 쓴다)
 *   TDC_DEBUG_JLINK_ENTRY(k, id, s)          header 항목 k 에 블록 s 의 번호, 시작, 크기, word_bytes
 *   TDC_DEBUG_JLINK_TABLE(s)                 블록 s 의 table_size
 *   TDC_DEBUG_JLINK_MEMBER(s, i, off, cnt)   블록 s 의 멤버 표 i 번째 */
#define TDC_DEBUG_JLINK_ENTRY(k, id_, s)                                                                                                                       \
    do                                                                                                                                                         \
    {                                                                                                                                                          \
        TDC_DEBUG_JLINK_AREA->header.entry[k].id         = (id_);                                                                                              \
        TDC_DEBUG_JLINK_AREA->header.entry[k].start      = TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_area_t, s);                                                    \
        TDC_DEBUG_JLINK_AREA->header.entry[k].size       = TDC_DEBUG_JLINK_WSIZE(tdc_debug_jlink_area_t, s);                                                   \
        TDC_DEBUG_JLINK_AREA->header.entry[k].word_bytes = TDC_DEBUG_JLINK_CFX_WORD_BYTES;                                                                     \
    } while (0)

#define TDC_DEBUG_JLINK_TABLE(s) (TDC_DEBUG_JLINK_AREA->s.table_size = TDC_DEBUG_JLINK_WSIZE(tdc_debug_jlink_area_t, s.table))

#define TDC_DEBUG_JLINK_MEMBER(s, i, off, cnt)                                                                                                                 \
    do                                                                                                                                                         \
    {                                                                                                                                                          \
        TDC_DEBUG_JLINK_AREA->s.table[i].offset = (off);                                                                                                       \
        TDC_DEBUG_JLINK_AREA->s.table[i].count  = (cnt);                                                                                                       \
    } while (0)

/* CM3 에 알린다 (CFX_3_IRQn). CM3 ISR 이 DCRDR 값을 바꾸고 PC 는 그것을 보고 켜 둔 블록의 flag 를 읽는다.
 * 블록의 flag 를 바꾼 뒤에 부른다 (기록은 세운 뒤, 주입은 내린 뒤) */
#define TDC_DEBUG_JLINK_NOTIFY() (D_CM3->CMDS = CM3_CMD_3)

/* 한 번에 초기화: ARAM2/3 전원 -> magic 0 -> 영역 0 -> header 크기 -> 등록 -> magic.
 * normal_init() 에서 부른다 (standby 복귀마다 다시 돈다) */
void tdc_debug_jlink_init(void);

/* 등록. 블록을 더하면 여기에 줄을 더한다 (tdc_debug_jlink_init 이 부른다) */
void tdc_debug_jlink_register(void);

/* 블록 동작 (main.c 에서 부른다. 그 블록의 enable 이 1 일 때만 부른다) */
void tdc_debug_jlink_dmic(int use_earpiece); /* 믹서 다음, dmic_enable 1 일 때: dmic_inj_enable 0 이면 입력 FIFO 16 샘플 기록, 1 이면 믹서 결과를 주입 샘플로 바꾼다 */
void tdc_debug_jlink_vmag_capture(void);     /* 대표값 계산 뒤 (분기 맨 아래), vmag_enable 1 일 때: 32 개 기록 */

#endif  // __tdc_debug_jlink_h__
