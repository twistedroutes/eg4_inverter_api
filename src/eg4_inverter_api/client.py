if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import asyncio
import logging

import aiohttp

from eg4_inverter_api.constants import (
    INVERTER_BATTERY_ENDPOINT,
    INVERTER_ENERGY_ENDPOINT,
    INVERTER_RUNTIME_ENDPOINT,
    LOGIN_ENDPOINT,
)
from eg4_inverter_api.exceptions import EG4APIError, EG4AuthError
from eg4_inverter_api.models import (
    APIResponse,
    BatteryData,
    BatteryUnit,
    EnergyData,
    Inverter,
    RuntimeData,
)


class EG4InverterAPI:
    """Asynchronous EG4 API client."""

    def __init__(
        self, username, password, serialNum=None, plantId=None, base_url=None
    ) -> None:
        self._username = username
        self._password = password
        self._session = None
        self.jsessionid = None
        self._inverters = []
        self._plantId = plantId
        self._serialNum = serialNum
        self._base_url = base_url or "https://monitor.eg4electronics.com"

        # Endpoint references
        self._login_url = f"{self._base_url}{LOGIN_ENDPOINT}"
        self._inverter_runtime_url = f"{self._base_url}{INVERTER_RUNTIME_ENDPOINT}"
        self._inverter_energy_url = f"{self._base_url}{INVERTER_ENERGY_ENDPOINT}"
        self._inverter_battery_url = f"{self._base_url}{INVERTER_BATTERY_ENDPOINT}"

    async def _get_session(self, ignore_ssl=False):
        """Initialize an aiohttp session."""
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        do_ssl = not ignore_ssl

        if self._session is None:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=do_ssl),
                headers=headers
            )
        return self._session

    async def login(self, ignore_ssl=False) -> None:
        """Authenticate and retrieve session cookie."""
        session = await self._get_session(ignore_ssl)

        payload = f"account={self._username}&password={self._password}"
        async with session.post(self._login_url, data=payload) as response:
            if response.status == 200:
                self.jsessionid = self._extract_jsessionid(response.cookies)
                inverter_data = await response.json()
                if "success" not in inverter_data or inverter_data["success"] is not True:
                    raise EG4AuthError("Login failed. Please check your credentials.")
                self._inverters = self._extract_inverters(inverter_data)
                logging.info(f"Login successful for user {self._username}")
            else:
                raise EG4AuthError("Login failed. Please check your credentials.")

    def _extract_jsessionid(self, cookies):
        """Extract JSESSIONID from cookies."""
        for key, cookie in cookies.items():
            if key == "JSESSIONID":
                return cookie.value
        raise EG4AuthError("Failed to retrieve JSESSIONID during login.")

    def _extract_inverters(self, data):
        """Extract available inverters from the login response."""
        inverters = []

        for plant in data.get("plants", []):
            plantId = plant.get("plantId")
            plant_name = plant.get("name")
            for inverter in plant.get("inverters", []):
                inverter = Inverter(
                    plantId=plantId,
                    plantName=plant_name,
                    captureExtra=True,
                    **inverter,
                )
                inverters.append(inverter)

        if not inverters:
            raise EG4APIError("No inverters found in the response data.")

        return inverters

    async def _request(self, method, url, payload=None):
        """Unified async request method with automatic reauthentication."""
        if not self.jsessionid:
            await self.login()

        session = await self._get_session()

        headers = {"Cookie": f"JSESSIONID={self.jsessionid}"}
        async with session.request(
            method, url, headers=headers, data=payload
        ) as response:
            if response.status == 401:
                await self.login()  # Re-authenticate on 401
                async with session.request(
                    method, url, headers=headers, data=payload
                ) as retry_response:
                    if retry_response.status != 200:
                        raise EG4APIError(
                            f"API request failed: {retry_response.status}"
                        )
                    return await retry_response.json()

            if response.status != 200:
                raise EG4APIError(
                    f"API request failed: {response.status} - {await response.text()}"
                )

            return await response.json()

    async def get_inverter_runtime_async(self, captureExtra=True):
        """Retrieve inverter runtime data."""
        payload = f"serialNum={self._serialNum}"
        response = await self._request("POST", self._inverter_runtime_url, payload)

        if response.get("success"):
            return RuntimeData(captureExtra=captureExtra, **response)
        else:
            return APIResponse(success=False, error_message=response.get("error"))

    async def get_inverter_energy_async(self, captureExtra=True):
        """Retrieve inverter energy data."""
        payload = f"serialNum={self._serialNum}"
        response = await self._request("POST", self._inverter_energy_url, payload)
        if response.get("success"):
            return EnergyData(captureExtra=captureExtra, **response)
        else:
            return APIResponse(success=False, error_message=response.get("error"))

    async def get_inverter_battery_async(self, captureExtra=True):
        """Retrieve inverter battery data."""
        payload = f"serialNum={self._serialNum}"
        response = await self._request("POST", self._inverter_battery_url, payload)

        if response.get("success"):
            # Extract battery units
            battery_units = [
                BatteryUnit(captureExtra=captureExtra, **unit)
                for unit in response.get("batteryArray", [])
            ]

            # Extract overall battery data
            return BatteryData(
                remainCapacity=response.get("remainCapacity"),
                fullCapacity=response.get("fullCapacity"),
                totalNumber=response.get("totalNumber"),
                totalVoltageText=response.get("totalVoltageText"),
                currentText=response.get("currentText"),
                battery_units=battery_units,
            )
        else:
            return APIResponse(success=False, error_message=response.get("error"))

    async def close(self):
        """Close the aiohttp session when done."""
        if self._session:
            await self._session.close()

    # --------- SYNC WRAPPERS ---------
    def get_inverter_runtime(self, captureExtra=True):
        """Sync wrapper for inverter runtime data."""
        return asyncio.run(self.get_inverter_runtime_async(captureExtra))

    def get_inverter_energy(self, captureExtra=True):
        """Sync wrapper for inverter energy data."""
        return asyncio.run(self.get_inverter_energy_async(captureExtra))

    def get_inverter_battery(self, captureExtra=True):
        """Sync wrapper for inverter battery data."""
        return asyncio.run(self.get_inverter_battery_async(captureExtra))

    # --------- SYNC FUNCTIONS  ---------
    def get_inverters(self):
        """Show the list of inverters."""
        return self._inverters

    def set_selected_inverter(
        self, plantId=None, serialNum=None, inverterIndex=None
    ) -> None:
        """Set the plantId and serialNum."""
        
        if plantId is not None and serialNum is not None:
            self._plantId = plantId
            self._serialNum = serialNum
        elif inverterIndex is not None and len(self._inverters) > inverterIndex:
            inverter = self._inverters[inverterIndex]
            self._plantId = inverter.plantId
            self._serialNum = inverter.serialNum
        else:
            raise EG4APIError("No Inverter or Plant/Serial selection")


# --------- MAIN EXECUTION BLOCK FOR TESTING ---------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,  # Show INFO and above
        format="%(asctime)s - %(levelname)s - %(message)s",  # Clear timestamped format
    )
    import os
    from dotenv import load_dotenv

    load_dotenv()

    async def test():
        USERNAME = os.getenv("EG4_USERNAME")
        PASSWORD = os.getenv("EG4_PASSWORD")
        SERIAL_NUMBER = os.getenv("EG4_SERIAL_NUMBER")
        PLANT_ID = os.getenv("EG4_PLANT_ID")
        BASE_URL = os.getenv("EG4_BASE_URL", "https://monitor.eg4electronics.com")
        IGNORE_SSL = os.getenv("EG4_DISABLE_VERIFY_SSL", "0") == "1"
        
        # api = EG4InverterAPI(USERNAME, PASSWORD, serialNum, plantId)
        api = EG4InverterAPI(USERNAME, PASSWORD, BASE_URL)

        try:
            await api.login(ignore_ssl=IGNORE_SSL)  # noqa: SLF001
            api.set_selected_inverter(inverterIndex=0)

            # Show available inverters
            logging.info("Inverters Found:")
            for index, inverter in enumerate(api.get_inverters()):
                logging.info(f"  {index} - {inverter}")  # noqa: G004

            # Runtime Data
            runtime_data = await api.get_inverter_runtime_async()
            logging.info(f"\nInverter Runtime Data:\n{runtime_data}")

            # Energy Data
            energy_data = await api.get_inverter_energy_async()
            logging.info(f"\nInverter Energy Data:\n{energy_data}")

            # Battery Data
            battery_data = await api.get_inverter_battery_async()
            logging.info(f"\nBattery Data:\n{battery_data}")
            for unit in battery_data.battery_units:
                logging.info(f"\t{unit}")

        except EG4AuthError as auth_err:
            logging.error(f"❌ Authentication Error: {auth_err}")
        except EG4APIError as api_err:
            logging.error(f"❌ API Error: {api_err}")
        except Exception as e:
            logging.error(f"❌ Unexpected Error: {e}")
        finally:
            await api.close()

    asyncio.run(test())
