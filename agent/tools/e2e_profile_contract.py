"""Typed contract for the legacy Job-workload e2e adapter."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

JOB_WORKLOAD_VALIDATOR = "job-workload-v1"

class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CustomResourceContract(ContractModel):
    resource: str = Field(min_length=1)
    crdName: str = Field(min_length=1)


class EnvironmentContract(ContractModel):
    datasetPath: str = Field(min_length=1)
    outputPath: str = Field(min_length=1)


class PvcContract(ContractModel):
    nameFrom: Literal["spec.pvcName"]
    mountPath: str = Field(min_length=1)
    volumeName: str = Field(min_length=1)
    storage: str = Field(min_length=1)


class JobWorkloadE2EContract(ContractModel):
    validator: Literal["job-workload-v1"]
    clusterName: str = Field(min_length=1)
    samplePath: str = Field(min_length=1)
    customResource: CustomResourceContract
    gpuResourceName: str = Field(min_length=1)
    envNames: EnvironmentContract
    pvc: PvcContract


class JobSpecValidationContract(ContractModel):
    jobNameTemplate: str = Field(min_length=1)
    podSelectorTemplate: str = Field(min_length=1)
    checks: list[dict[str, Any]] = Field(min_length=1)


class PendingWarningContract(ContractModel):
    enabled: bool
    match: list[str] = Field(min_length=1)
    message: str = Field(min_length=1)


class WarningContract(ContractModel):
    gpuPending: PendingWarningContract


class LegacyJobE2EProfile(ContractModel):
    profileName: str = Field(min_length=1)
    managedResources: list[str] = Field(min_length=1)
    referencedResources: list[str] = Field(min_length=1)
    sampleDefaults: dict[str, Any] = Field(default_factory=dict)
    e2e: JobWorkloadE2EContract
    jobSpecValidation: JobSpecValidationContract
    warnings: WarningContract

    @model_validator(mode="after")
    def validate_adapter_capabilities(self) -> "LegacyJobE2EProfile":
        if "Job" not in self.managedResources:
            raise ValueError(
                f"{JOB_WORKLOAD_VALIDATOR} requires Job in managedResources"
            )
        missing = {
            "Pod",
            "PersistentVolumeClaim",
        } - set(self.referencedResources)
        if missing:
            raise ValueError(
                f"{JOB_WORKLOAD_VALIDATOR} requires referencedResources: "
                + ", ".join(sorted(missing))
            )
        return self


class SampleMetadata(ContractModel):
    name: str = Field(min_length=1)


class JobWorkloadSpec(ContractModel):
    image: str = Field(min_length=1)
    gpuCount: int = Field(ge=0)
    pvcName: str = Field(min_length=1)
    datasetPath: str = Field(min_length=1)
    outputPath: str = Field(min_length=1)


class JobWorkloadSample(ContractModel):
    metadata: SampleMetadata
    spec: JobWorkloadSpec
