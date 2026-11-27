# v0.921 프리징 진단 안내

**추가 제보에서 같은 기기·같은 설정의 일본판 원본은 정상이고, v0.921은 동일한 오프닝 무음·정지 증상이라고 확인됐습니다.** 아래 진단용 패처로 원인을 분리하고 있습니다. 원인을 확정하거나 문제가 해결된 버전으로 표시하지 않습니다.

## 프리징 재시험 결과와 진단 패처

**진단용이며 수정 완료본이 아닙니다.** 기존 v0.921 EXE·ZIP·Xdelta는 그대로 보존하고, 같은 릴리스에 A/B/C 선택형 진단 패처를 추가했습니다.

[진단 EXE 다운로드](https://github.com/OldManCraveGuitars-bit/GC-Viewtiful-Joe-Revival-Kr/releases/download/v0.921/Viewtiful-Joe-Revival-Kr-Freeze-Diagnostics.exe) · [진단 ZIP](https://github.com/OldManCraveGuitars-bit/GC-Viewtiful-Joe-Revival-Kr/releases/download/v0.921/Viewtiful-Joe-Revival-Kr-Freeze-Diagnostics.zip) · [사용법 TXT](https://github.com/OldManCraveGuitars-bit/GC-Viewtiful-Joe-Revival-Kr/releases/download/v0.921/Freeze-Diagnostics-README-KR.txt) · [진단 SHA-256](https://github.com/OldManCraveGuitars-bit/GC-Viewtiful-Joe-Revival-Kr/releases/download/v0.921/Freeze-Diagnostics-SHA256SUMS.txt)

| 모드 | 원복 범위 |
| --- | --- |
| A | 추가 자막 실행만 원본 호출로 복원. 한글 메뉴·이미지와 추가 메모리 배치는 유지합니다. |
| B | A에 더해 자막 코드·데이터 로딩과 메모리 예약을 제거합니다. 한글 메뉴·이미지는 유지합니다. |
| C | 실행 DOL 전체를 일본판 원본으로 복원하고 한글 이미지·텍스처를 유지합니다. 일부 글자 메뉴는 영어입니다. |

1. **수정되지 않은 일본판 GVFJ08 원본 ISO/GCM**에 적용합니다. 기존 한글 롬에 덧씌우지 않습니다.
2. EXE에서 **A부터 선택**해 멈추던 장면과 오프닝 음성을 확인합니다. 동일하면 B, B도 동일하면 C 순서로 비교합니다. 각각 새 ISO로 저장합니다.
3. 결과를 `A: 음성 정상/무음, 진행/멈춤` 형식으로 기록해 주세요. 정상 진행되는 단계가 있으면 그 결과부터 확인합니다.

A에서 정상이라면 자막 실행 경로를, B부터 정상이라면 자막 메모리·추가 로드 구역을 좁혀 볼 수 있습니다. C에서만 정상이라면 나머지 실행 코드 확장을, C도 동일하면 이미지 자원·디스크 배치를 더 조사합니다. 이 결과만으로 특정 원인이 단독 입증되지는 않습니다.

추가 자막과 일부 메뉴 한글화는 **진단을 위해서만** 원복됩니다. 승인한 한글화 원고·이미지를 삭제하거나 기존 공개본을 교체한 것이 아닙니다. 원본 영상·음성 파일과 위치를 보존하며 재인코딩하지 않았습니다.

검수는 A/B/C 각각 부팅부터 약 60초(메뉴 포함)의 캐시·MMU·저수준 DSP 에뮬레이터 관찰, A의 완성 EXE 실제 적용, B/C 전체 디코드 결과 해시 대조입니다. **제보 기기에서의 해결 확인이나 전체 오프닝 통과 검증은 아닙니다.**

진단 EXE SHA-256: `86e19b3206aaae7c283d540e1d2e2bcd0a7007970a5149bf163dd46f25402e91`

진단 ZIP SHA-256: `a2e18bea5947dfbb188d58c76680a825178e131e68d81aa6b715a081e6a0f5a2`
