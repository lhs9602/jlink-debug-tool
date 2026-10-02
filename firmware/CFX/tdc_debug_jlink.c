/**
 * @file tdc_debug_jlink.c
 * @brief J-Link 디버그 블록: 초기화, 등록, 블록 동작 (DMIC 기록과 주입, vMag).
 *        블록 정의와 동작 규칙은 tdc_debug_jlink.h 의 정의 주석 참조.
 */

#include <main.h>              /* main.h 가 tdc_debug_jlink.h 를 포함한다 */
#include <FrequencyAnalysis.h> /* g_freq_rep_values (vMag) */

#if TDC_DEBUG_JLINK_ENABLE

/* ---------------------------------------------------------------------------
 * 초기화
 * ------------------------------------------------------------------------- */
#define TDC_DEBUG_JLINK_AREA_WORDS ((int) sizeof(tdc_debug_jlink_area_t))

void tdc_debug_jlink_init(void)
{
    volatile int _IOMEM *p_area = (volatile int _IOMEM *) TDC_DEBUG_JLINK_BASE;

    /* 1.5 는 LPDSP32 이미지가 없어 부트로더가 ARAM2/3 전원을 켜지 않을 수 있다.
     * Sys_Memory_Enable() 은 비트를 더하기만 하므로 다른 메모리에는 영향이 없다 (shared/mem_cfg.h) */
    Sys_Memory_Enable(DSP_ARAM2_POWER_ENABLE | DSP_ARAM3_POWER_ENABLE, 0);

    /* 초기화 중에는 PC 가 "디버그 블록 없음" 으로 보도록 magic 부터 내린다 */
    TDC_DEBUG_JLINK_AREA->header.magic = 0;

    /* 영역 전체를 0 으로 (magic 칸 다음부터). 데이터 초기값은 0 이다 */
    for (register int i = 1; i < TDC_DEBUG_JLINK_AREA_WORDS; i++)
        chess_loop_range(TDC_DEBUG_JLINK_AREA_WORDS - 1, TDC_DEBUG_JLINK_AREA_WORDS - 1)
        {
            p_area[i] = 0;
        }

    TDC_DEBUG_JLINK_AREA->header.size = (unsigned int) sizeof(tdc_debug_jlink_header_t);

    /* header 항목과 각 블록의 멤버 표 (아래 tdc_debug_jlink_register) */
    tdc_debug_jlink_register();

    /* 0 이 아닌 초기값이 필요하면 여기서 넣는다 (지금은 없다) */

    /* 마지막에 magic. 이제 PC 가 읽어도 된다 */
    TDC_DEBUG_JLINK_AREA->header.magic = TDC_DEBUG_JLINK_MAGIC;
}

/* ---------------------------------------------------------------------------
 * 등록 (블록 더하기 4 단계). tdc_debug_jlink_init() 이 영역을 0 으로 지운 뒤, magic 을 쓰기 전에 부른다
 * ------------------------------------------------------------------------- */
void tdc_debug_jlink_register(void)
{
    /* 등록: 항목 번호, 블록 번호, 영역 안 이름 */
    TDC_DEBUG_JLINK_ENTRY(0, TDC_DEBUG_JLINK_ID_DMIC, dmic);
    TDC_DEBUG_JLINK_ENTRY(1, TDC_DEBUG_JLINK_ID_VMAG, vmag);
    TDC_DEBUG_JLINK_ENTRY(2, TDC_DEBUG_JLINK_ID_IFFT, ifft);

    /* DMIC 멤버 표: 순번, 시작 칸, 칸 수 */
    TDC_DEBUG_JLINK_TABLE(dmic);
    TDC_DEBUG_JLINK_MEMBER(dmic, 0, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_buf_full), 2);
    TDC_DEBUG_JLINK_MEMBER(dmic, 1, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_pos), 1);
    TDC_DEBUG_JLINK_MEMBER(dmic, 2, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_cur_buf), 1);
    TDC_DEBUG_JLINK_MEMBER(dmic, 3, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_missing_cnt), 1);
    TDC_DEBUG_JLINK_MEMBER(dmic, 4, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_buf), TDC_DEBUG_JLINK_DMIC_LEN);
    TDC_DEBUG_JLINK_MEMBER(dmic, 5, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_buf) + TDC_DEBUG_JLINK_DMIC_LEN, TDC_DEBUG_JLINK_DMIC_LEN);
    TDC_DEBUG_JLINK_MEMBER(dmic, 6, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_inj_enable), 1);
    TDC_DEBUG_JLINK_MEMBER(dmic, 7, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_dmic_t, dmic_enable), 1);

    /* vMag 멤버 표 */
    TDC_DEBUG_JLINK_TABLE(vmag);
    TDC_DEBUG_JLINK_MEMBER(vmag, 0, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_buf_full), 2);
    TDC_DEBUG_JLINK_MEMBER(vmag, 1, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_write_pos), 1);
    TDC_DEBUG_JLINK_MEMBER(vmag, 2, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_write_buf), 1);
    TDC_DEBUG_JLINK_MEMBER(vmag, 3, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_missing_cnt), 1);
    TDC_DEBUG_JLINK_MEMBER(vmag, 4, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_buf), TDC_DEBUG_JLINK_VMAG_LEN);
    TDC_DEBUG_JLINK_MEMBER(vmag, 5, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_buf) + TDC_DEBUG_JLINK_VMAG_LEN, TDC_DEBUG_JLINK_VMAG_LEN);
    TDC_DEBUG_JLINK_MEMBER(vmag, 6, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_vmag_t, vmag_enable), 1);

    /* IFFT 멤버 표 */
    TDC_DEBUG_JLINK_TABLE(ifft);
    TDC_DEBUG_JLINK_MEMBER(ifft, 0, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_buf_full), 2);
    TDC_DEBUG_JLINK_MEMBER(ifft, 1, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_pos), 1);
    TDC_DEBUG_JLINK_MEMBER(ifft, 2, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_cur_buf), 1);
    TDC_DEBUG_JLINK_MEMBER(ifft, 3, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_missing_cnt), 1);
    TDC_DEBUG_JLINK_MEMBER(ifft, 4, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_ref_buf), TDC_DEBUG_JLINK_IFFT_LEN);
    TDC_DEBUG_JLINK_MEMBER(ifft, 5, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_ref_buf) + TDC_DEBUG_JLINK_IFFT_LEN, TDC_DEBUG_JLINK_IFFT_LEN);
    TDC_DEBUG_JLINK_MEMBER(ifft, 6, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_out_buf), TDC_DEBUG_JLINK_IFFT_LEN);
    TDC_DEBUG_JLINK_MEMBER(ifft, 7, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_out_buf) + TDC_DEBUG_JLINK_IFFT_LEN, TDC_DEBUG_JLINK_IFFT_LEN);
    TDC_DEBUG_JLINK_MEMBER(ifft, 8, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_mode_cnt), 2);
    TDC_DEBUG_JLINK_MEMBER(ifft, 9, TDC_DEBUG_JLINK_WOFF(tdc_debug_jlink_ifft_t, ifft_enable), 1);
}

/* ---------------------------------------------------------------------------
 * 블록 1: DMIC. 더블 버퍼 핸드셰이크. main.c 는 dmic_enable 이 1 일 때 tdc_debug_jlink_dmic() 하나만 부르고,
 * 그 안에서 dmic_inj_enable 로 방향을 고른다 (0 기록, 1 주입)
 * 기록은 버퍼가 두 개인 것과 missing_cnt 말고는 동료 sound1-dnn 의 td_dnn_extract_dmic() 과 같다.
 * 주입은 믹서 결과를 덮어쓴다 (믹서 뒤, 동료 sound1-dnn 의 td_dnn_bypass_mic() 과 같은 자리).
 * 믹서를 건너뛰므로 입력 LPF (2-tap 이동평균) 는 주입 함수 안에서 같은 식으로 건다 (마이크에 걸리는 1 ms 에만).
 * ------------------------------------------------------------------------- */

/* 기록 (dmic_inj_enable 0 일 때). use_earpiece 가 0 이면 DMIC(FIFO A0_0), 1 이면 이어피스(FIFO A0_1) 16 샘플을 쓴다 */
static void tdc_debug_jlink_dmic_capture(int use_earpiece)
{
    int _XMEM *p_src;
    int w = TDC_DEBUG_JLINK_AREA->dmic.dmic_cur_buf;

    if (TDC_DEBUG_JLINK_AREA->dmic.dmic_buf_full[w] != 0)
    {
        /* 두 버퍼가 다 찼다 (PC 가 아직 읽지 않았다). 이번 1 ms (16 샘플) 는 기록되지 않는다. 그 횟수를 센다 */
        TDC_DEBUG_JLINK_AREA->dmic.dmic_missing_cnt++;
        return;
    }

    if (use_earpiece)
    {
        p_src = (int _XMEM *) &HCT_A0_1[0];
    }
    else
    {
        p_src = (int _XMEM *) &HCT_A0_0[0];
    }

    int local_pos = TDC_DEBUG_JLINK_AREA->dmic.dmic_pos;

    for (register int i = 0; i < df_inputADC_DataBuffLength; i++)
        chess_loop_range(df_inputADC_DataBuffLength, df_inputADC_DataBuffLength)
        {
            TDC_DEBUG_JLINK_AREA->dmic.dmic_buf[w][local_pos++] = p_src[i];
        }

    if (local_pos >= TDC_DEBUG_JLINK_DMIC_LEN)
    {
        TDC_DEBUG_JLINK_AREA->dmic.dmic_pos         = 0;
        TDC_DEBUG_JLINK_AREA->dmic.dmic_buf_full[w] = 1;     /* 다 찼다. PC 가 읽고 0 을 쓴다 */
        TDC_DEBUG_JLINK_AREA->dmic.dmic_cur_buf     = 1 - w; /* 다른 버퍼로 옮긴다. 비어 있으면 멈추지 않고 이어서 쓴다 */
        TDC_DEBUG_JLINK_NOTIFY();                            /* flag 를 세운 뒤에 알린다 */
    }
    else
    {
        TDC_DEBUG_JLINK_AREA->dmic.dmic_pos = local_pos;
    }
}

/* 주입의 입력 LPF 용: 직전 주입 샘플 (시프트 전). 다 꺼낸 버퍼는 PC 가 다시 채우므로 따로 둔다. 무음과 기록 중에는 0 */
static int _XMEM s_tdc_debug_jlink_inj_prev = 0;

/* 주입 (dmic_inj_enable 1 일 때). 믹서 결과를 주입 샘플 16 개로 바꾼다.
 * use_lpf 가 1 이면 audio_mix_internal_mic_only_2_tap_moving_average_lpf() 와 같은 식으로 직전 샘플과 평균한다 */
static void tdc_debug_jlink_dmic_inject(int use_lpf)
{
    int _XMEM *p_mix = (int _XMEM *) HEAR_ADDR_AUDIO_MIX;
    int prev = s_tdc_debug_jlink_inj_prev;
    int cur;
    int w = TDC_DEBUG_JLINK_AREA->dmic.dmic_cur_buf;         /* 꺼낼 버퍼 (0 / 1) */
    int local_pos = TDC_DEBUG_JLINK_AREA->dmic.dmic_pos;     /* 그 버퍼 안의 다음 위치 (0 ~ 511) */
    int full = TDC_DEBUG_JLINK_AREA->dmic.dmic_buf_full[w];  /* 1 = PC 가 채웠다, 0 = 아직 비어 있다 */

    /* 버퍼는 시간 순서, 믹서 결과는 FIFO 순서 (인덱스 0 이 가장 최근) 라 뒤집어 넣는다.
     * 믹서와 같은 단위로 맞춘다 (audio_mix_internal_mic_only 와 같은 시프트) */
    for (register int i = 0; i < df_inputADC_DataBuffLength; i++)
        chess_loop_range(df_inputADC_DataBuffLength, df_inputADC_DataBuffLength)
        {
            if (full == 0)
            {
                p_mix[i] = 0; /* 꺼낼 샘플이 없다: 무음 */
            }
            else
            {
                cur = TDC_DEBUG_JLINK_AREA->dmic.dmic_buf[w][local_pos + i];

                if (use_lpf)
                {
                    p_mix[(df_inputADC_DataBuffLength - 1) - i] = (cur + prev) >> (AUDIO_INPUT_RSHIFT + 1);
                }
                else
                {
                    p_mix[(df_inputADC_DataBuffLength - 1) - i] = cur >> AUDIO_INPUT_RSHIFT;
                }

                prev = cur;
            }
        }

    if (full == 0)
    {
        /* PC 가 아직 채우지 않았다 (늦었다). dmic_pos, dmic_cur_buf 는 그대로 두고 기다린다. 그 횟수를 센다 (기록과 같은 칸) */
        s_tdc_debug_jlink_inj_prev = 0;
        TDC_DEBUG_JLINK_AREA->dmic.dmic_missing_cnt++;
        return;
    }

    s_tdc_debug_jlink_inj_prev = prev;

    local_pos = local_pos + df_inputADC_DataBuffLength;

    if (local_pos >= TDC_DEBUG_JLINK_DMIC_LEN)
    {
        TDC_DEBUG_JLINK_AREA->dmic.dmic_pos         = 0;
        TDC_DEBUG_JLINK_AREA->dmic.dmic_buf_full[w] = 0;     /* 다 꺼냈다. PC 가 채우고 1 을 쓴다 */
        TDC_DEBUG_JLINK_AREA->dmic.dmic_cur_buf     = 1 - w; /* 다른 버퍼로 옮긴다. 비어 있으면 PC 가 채울 때까지 무음 */
        TDC_DEBUG_JLINK_NOTIFY();                            /* flag 를 내린 뒤에 알린다 */
    }
    else
    {
        TDC_DEBUG_JLINK_AREA->dmic.dmic_pos = local_pos;
    }
}

/* DMIC: 믹서(audio_mix_*) 가 입력 FIFO 를 읽은 다음, AGC 전처리 호출 앞에서 1 ms 마다 부른다.
 * LiveStimulation 모드, dmic_enable 1 일 때만 부른다 (main.c). dmic_inj_enable 로 기록과 주입 가운데 하나를 한다 */
void tdc_debug_jlink_dmic(int use_earpiece)
{
    if (TDC_DEBUG_JLINK_AREA->dmic.dmic_inj_enable == 0)
    {
        s_tdc_debug_jlink_inj_prev = 0; /* 주입을 다시 켠 첫 샘플에 앞 주입의 값이 섞이지 않게 */
        tdc_debug_jlink_dmic_capture(use_earpiece);
    }
    else
    {
#if TDC_2_TAP_MOVING_AVERAGE_LPF_ENABLE
        /* g_2_tap_lpf_active 는 main.c 가 이번 1 ms 의 믹서 앞에서 정한다 (이어피스 가지에서는 갱신하지 않아 따로 본다) */
        tdc_debug_jlink_dmic_inject((use_earpiece == 0) && (g_2_tap_lpf_active != 0));
#else
        tdc_debug_jlink_dmic_inject(0);
#endif
    }
}

/* ---------------------------------------------------------------------------
 * 블록 2: vMag (밴드 대표값 32 개, 더블 버퍼)
 * ------------------------------------------------------------------------- */

/* 대표값 계산(find_freq_rep_value) 뒤, 그 분기 맨 아래에서 1 ms 마다 부른다 (vmag_enable 1 일 때만, main.c) */
void tdc_debug_jlink_vmag_capture(void)
{
    int w = TDC_DEBUG_JLINK_AREA->vmag.vmag_write_buf;

    if (TDC_DEBUG_JLINK_AREA->vmag.vmag_buf_full[w] != 0)
    {
        /* 두 버퍼가 다 찼다 (PC 가 아직 읽지 않았다). 이번 1 ms 는 기록되지 않는다 */
        TDC_DEBUG_JLINK_AREA->vmag.vmag_missing_cnt++;
        return;
    }

    int local_pos = TDC_DEBUG_JLINK_AREA->vmag.vmag_write_pos;

    for (register int i = 0; i < TDC_DEBUG_JLINK_VMAG_BANDS; i++)
        chess_loop_range(TDC_DEBUG_JLINK_VMAG_BANDS, TDC_DEBUG_JLINK_VMAG_BANDS)
        {
            TDC_DEBUG_JLINK_AREA->vmag.vmag_buf[w][local_pos++] = g_freq_rep_values[i];
        }

    if (local_pos >= TDC_DEBUG_JLINK_VMAG_LEN)
    {
        TDC_DEBUG_JLINK_AREA->vmag.vmag_write_pos   = 0;
        TDC_DEBUG_JLINK_AREA->vmag.vmag_buf_full[w] = 1;     /* 다 찼다. PC 가 읽고 0 을 쓴다 */
        TDC_DEBUG_JLINK_AREA->vmag.vmag_write_buf   = 1 - w; /* 다른 버퍼로 옮겨 이어 쓴다 */
        TDC_DEBUG_JLINK_NOTIFY();                            /* flag 를 세운 뒤에 알린다 */
    }
    else
    {
        TDC_DEBUG_JLINK_AREA->vmag.vmag_write_pos = local_pos;
    }
}

/* ---------------------------------------------------------------------------
 * 블록 3: IFFT (기준 = AGC 출력, 출력 = DAC 로 낸 16 샘플. 같은 위치에 나란히 쓰는 더블 버퍼)
 * ------------------------------------------------------------------------- */

/* 1 ms 처리의 맨 끝에서 부른다 (ifft_enable 1 일 때만, main.c).
 * p_ref: 기준 16 샘플 (기존 경로가 DAC 로 내는 것), p_out: 이번 1 ms 에 DAC 로 낸 16 샘플. 둘 다 main.c 가 넘긴다.
 * ifft_on 은 이번 1 ms 가 IFFT 오디오 모드였는지 */
void tdc_debug_jlink_ifft_capture(int _XMEM *p_ref, int _XMEM *p_out, int ifft_on)
{
    int w = TDC_DEBUG_JLINK_AREA->ifft.ifft_cur_buf;

    if (TDC_DEBUG_JLINK_AREA->ifft.ifft_buf_full[w] != 0)
    {
        /* 두 버퍼가 다 찼다 (PC 가 아직 읽지 않았다). 이번 1 ms 는 기록되지 않는다 */
        TDC_DEBUG_JLINK_AREA->ifft.ifft_missing_cnt++;
        return;
    }

    int local_pos = TDC_DEBUG_JLINK_AREA->ifft.ifft_pos;

    if (local_pos == 0)
    {
        TDC_DEBUG_JLINK_AREA->ifft.ifft_mode_cnt[w] = 0; /* 이 버퍼를 처음부터 채운다 */
    }

    if (ifft_on)
    {
        TDC_DEBUG_JLINK_AREA->ifft.ifft_mode_cnt[w]++;
    }

    for (register int i = 0; i < df_inputADC_DataBuffLength; i++)
        chess_loop_range(df_inputADC_DataBuffLength, df_inputADC_DataBuffLength)
        {
            TDC_DEBUG_JLINK_AREA->ifft.ifft_ref_buf[w][local_pos + i] = p_ref[i];
            TDC_DEBUG_JLINK_AREA->ifft.ifft_out_buf[w][local_pos + i] = p_out[i];
        }

    local_pos = local_pos + df_inputADC_DataBuffLength;

    if (local_pos >= TDC_DEBUG_JLINK_IFFT_LEN)
    {
        TDC_DEBUG_JLINK_AREA->ifft.ifft_pos         = 0;
        TDC_DEBUG_JLINK_AREA->ifft.ifft_buf_full[w] = 1;     /* 다 찼다. PC 가 읽고 0 을 쓴다 */
        TDC_DEBUG_JLINK_AREA->ifft.ifft_cur_buf     = 1 - w; /* 다른 버퍼로 옮겨 이어 쓴다 */
        TDC_DEBUG_JLINK_NOTIFY();                            /* flag 를 세운 뒤에 알린다 */
    }
    else
    {
        TDC_DEBUG_JLINK_AREA->ifft.ifft_pos = local_pos;
    }
}

#endif  // TDC_DEBUG_JLINK_ENABLE
