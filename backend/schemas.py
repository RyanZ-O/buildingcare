from typing import Literal

from pydantic import BaseModel, Field


class StatusUpdate(BaseModel):
    status: Literal["submitted", "in_progress", "resolved"]


class AnalysisRequest(BaseModel):
    observations: str = Field(default="", max_length=10000)


class SimulationRequest(BaseModel):
    analysisId: str = Field(min_length=1, max_length=100)
    causeId: str = Field(min_length=1, max_length=100)
    action: Literal["observe", "local_repair", "system_shutdown"]
    parameters: 'PlanningInputs | None' = None


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    simulationId: str | None = Field(default=None, min_length=1, max_length=100)


class PlanningInputs(BaseModel):
    durationHours: float = Field(default=4, ge=0.25, le=168, allow_inf_nan=False)
    workers: int = Field(default=2, ge=1, le=50)
    hourlyRate: float = Field(default=45, ge=0, le=10000, allow_inf_nan=False)
    materialCost: float = Field(default=150, ge=0, le=1000000, allow_inf_nan=False)
    currency: Literal['SGD', 'EUR', 'USD', 'CNY'] = 'SGD'
    uncertaintyPercent: float = Field(default=25, ge=0, le=100, allow_inf_nan=False)
    isolationAssetId: str | None = Field(default=None, max_length=200)
    serviceState: Literal['ventilation_loss', 'cooling_loss', 'heating_loss', 'power_loss', 'water_loss'] = 'ventilation_loss'
    roomClosure: bool = False
    occupantsPerRoom: int = Field(default=2, ge=0, le=200)
    materialDescription: str = Field(default='Parts and consumables; verify specification on site', max_length=1000)
    repairMethod: Literal['standard', 'clean_adjust', 'replace'] = 'standard'
    coolingUnavailable: bool = False
    initialTemperature: float = Field(default=24, ge=-10, le=50, allow_inf_nan=False)
    outdoorTemperature: float = Field(default=32, ge=-30, le=55, allow_inf_nan=False)
    internalGainWatts: float = Field(default=300, ge=0, le=10000, allow_inf_nan=False)
    conductanceWattsPerK: float = Field(default=150, ge=10, le=5000, allow_inf_nan=False)
    capacitanceKwhPerK: float = Field(default=3, ge=0.1, le=200, allow_inf_nan=False)
    recoveryHours: float = Field(default=2, ge=0.25, le=48, allow_inf_nan=False)
    horizonHours: float = Field(default=24, ge=1, le=168, allow_inf_nan=False)
    comfortUpper: float = Field(default=28, ge=15, le=40, allow_inf_nan=False)


SimulationRequest.model_rebuild()


class LocateRequest(BaseModel):
    roomId: str = Field(min_length=1, max_length=200)
    system: Literal['hvac', 'electrical']
    text: str = Field(default='', max_length=10000)


class LocationUpdate(BaseModel):
    assetId: str | None = Field(default=None, max_length=200)
    locationDetail: str = Field(default='', max_length=1000)


class BindingRequest(BaseModel):
    analysisId: str = Field(max_length=100)
    causeId: str = Field(max_length=200)
    assetId: str = Field(max_length=200)
    reason: str = Field(min_length=5, max_length=1000)


class TopologyLink(BaseModel):
    sourceId: str = Field(min_length=1, max_length=200)
    targetId: str = Field(min_length=1, max_length=200)
    relation: Literal['SERVES', 'FEEDS', 'SUPPLIES_POWER', 'CONNECTED_TO']
    requires: Literal['ventilation_loss', 'cooling_loss', 'heating_loss', 'power_loss', 'water_loss']
    produces: Literal['ventilation_loss', 'cooling_loss', 'heating_loss', 'power_loss', 'water_loss']
    basis: Literal['assumption', 'verified'] = 'assumption'
    note: str = Field(min_length=5, max_length=2000)


class VisionRequest(BaseModel):
    usePhotos: bool = True


class InspectionRequest(BaseModel):
    analysisId: str = Field(min_length=1, max_length=100)
    causeId: str = Field(min_length=1, max_length=200)
    status: Literal['untested', 'investigating', 'ruled_out', 'confirmed']
    note: str = Field(min_length=5, max_length=2000)


class ResidentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    issueId: str | None = Field(default=None, max_length=100)
