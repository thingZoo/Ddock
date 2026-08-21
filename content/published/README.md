# Published D:ock content

이 폴더에는 Admin review와 publish validation을 통과한
`ddock_content_v0.1` 파일만 둡니다. Review draft인
`ddock_content_review_v0.1`은 이 폴더에 넣지 않습니다.

파일명은 다음 규칙을 사용합니다.

```text
{video_id}_ddock_content_v0_1.json
```

Admin 화면에서 내려받은 Publish Candidate는 repository root에서 다음 명령으로
가져옵니다.

```bash
npm run content:import -- ~/Downloads/G0d9CHLpnnc_ddock_content_v0_1.json
```

같은 영상 파일이 이미 있으면 기본적으로 중단합니다. 검토를 마친 교체 파일임을
확인한 경우에만 `--force`를 사용합니다.

```bash
npm run content:import -- ~/Downloads/G0d9CHLpnnc_ddock_content_v0_1.json --force
```

Python published validator가 canonical source of truth입니다. Frontend guard는
빌드와 개발 환경에서 잘못된 구조가 사용자에게 노출되는 것을 막는 최소 구조
검사이며 canonical validation을 대체하지 않습니다.
