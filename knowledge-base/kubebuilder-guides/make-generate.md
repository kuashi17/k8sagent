# make generate Guide

metadata:
- source: internal-authored
- category: guide
- topic: make generate controller-gen

## Purpose

`make generate`는 controller-gen을 사용해 deepcopy 코드를 생성한다.
API 타입 파일이 올바른 Go 코드여야 성공한다.

## Common Inputs

- `api/<version>/*_types.go`
- Go module files
- controller-gen binary

## Common Failures

`invalid field type`은 API struct에 잘못된 타입이 들어갔다는 의미다.
`notatype` 같은 값은 Go compiler와 controller-gen이 해석할 수 없다.
이 경우 controller-gen 재실행이 아니라 요구사항의 field type 또는 operator-spec을 수정해야 한다.

## Verification

성공하면 `api/<version>/zz_generated.deepcopy.go`가 생성 또는 갱신된다.
실패하면 stderr에서 파일 경로와 line number를 먼저 확인한다.

