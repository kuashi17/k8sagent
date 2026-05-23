# Kubebuilder Scaffold Workflow

## 목적

Kubebuilder 프로젝트 scaffold 생성 절차를 정의합니다.

## 흐름

1. 대상 작업 디렉터리를 확인합니다.
2. 프로젝트 이름과 module path를 결정합니다.
3. domain 값을 결정합니다.
4. Kubebuilder init 절차를 수행합니다.
5. API group, version, kind 값을 결정합니다.
6. Kubebuilder create api 절차를 수행합니다.
7. 생성된 디렉터리와 파일을 확인합니다.

## 산출물

- Kubebuilder 프로젝트 루트
- `api` 디렉터리
- `internal/controller` 디렉터리
- `config` 디렉터리
- `Makefile`
- `PROJECT`

