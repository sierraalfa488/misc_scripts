import copy
import os

import asyncio
import pymongo
import yaml

from bson.objectid import ObjectId
from typing import List
from random import randint
from motor import motor_asyncio
from core.config import settings



client = motor_asyncio.AsyncIOMotorClient(settings.DB_SERVER)
db = client['netadmin']

loop = asyncio.get_event_loop()

group_var_files = os.listdir("group_vars")
host_var_files = os.listdir("host_vars")


def rearrange_vxlan_vrf_data(vxlan_vrf: dict) -> List[dict]:
    reconstructed_vxlan_vrfs = []
    for k, v in vxlan_vrf.items():
        v["name"] = k
        v["site"] = "any"
        reconstructed_vxlan_vrfs.append(v)
    return reconstructed_vxlan_vrfs


async def seed_database_site_data(
    site_data: dict, file_name: str
) -> pymongo.results.InsertOneResult:
    await db.sites.create_index([("name", pymongo.ASCENDING)], unique=True)
    site_name = file_name.split(".")[0]
    site_data_truncated = dict()
    site_data_truncated["name"] = site_name
    for k, v in site_data.items():
        if type(v) is not dict:
            site_data_truncated.update({k: v})
    try:
        await db.sites.insert_one(site_data_truncated)
    except pymongo.errors.DuplicateKeyError:
        pass


async def seed_database_vxlan_vrfs(
    vxlan_vrfs: List[dict],
) -> List[pymongo.results.InsertOneResult]:
    await db.vrfs.create_index([("name", pymongo.ASCENDING)], unique=True)
    results = []
    for vxlan_vrf in vxlan_vrfs:
        new_vxlan_vrf = await db.vrfs.insert_one(vxlan_vrf)
        results.append(new_vxlan_vrf)
    return results


async def seed_database_vxlans(vxlans_data: dict, file_name: str):
    await db.vxlans.create_index(
        [("name", pymongo.ASCENDING), ("site", pymongo.ASCENDING)], unique=True
    )
    site_name = file_name.split(".")[0]
    site_in_db = await db.sites.find_one({"name": site_name})
    vxlans = list()
    for k, v in vxlans_data.items():
        v["name"] = k
        v["site"] = site_in_db["name"]
        vrf_in_db = await db.vrfs.find_one({"name": v["vrf_name"]})
        try:
            v["vrf"] = vrf_in_db["name"]
        except TypeError:
            v["vrf"] = None
        vxlans.append(v)
    for vxlan in vxlans:
        try:
            await db.vxlans.insert_one(vxlan)
        except pymongo.errors.DuplicateKeyError:
            pass


async def seed_database_devices(device_data: dict):
    await db.devices.create_index([("name", pymongo.ASCENDING)], unique=True)
    d_data = dict()
    for k, v in device_data.items():
        if k == "site":
            site_data = await db.sites.find_one({"name": v})
            v = site_data["name"]
            d_data.update({k: v})
        elif k == "other":
            try:
                d_data.update({"serial_number": v["serial_number"]})
            except KeyError:
                pass

        elif k == "hostname":
            d_data.update({"name": v})
        elif type(v) is str:
            d_data.update({k: v})
    try:
        await db.devices.insert_one(d_data)
    except pymongo.errors.DuplicateKeyError:
        pass
        # print(d_data)


async def main():
    await db.interfaces.create_index(
        [("name", pymongo.ASCENDING), ("device", pymongo.ASCENDING)], unique=True
    )
    for site in group_var_files:
        site_data_file = open(f"group_vars/{site}", "r")
        site_data_dict = yaml.load(site_data_file.read(), Loader=yaml.SafeLoader)
        site_data_file.close()

        # add site data to db
        await seed_database_site_data(site_data_dict, site)

        # add vxlan vrf data to db
        for k, v in site_data_dict.items():
            if k == "dc_vxlan_vrfs":
                vxlan_vrfs = rearrange_vxlan_vrf_data(v)
                try:
                    await seed_database_vxlan_vrfs(vxlan_vrfs)
                except pymongo.errors.DuplicateKeyError:
                    pass

        # add vxlan data to db
        for k, v in site_data_dict.items():
            if k == "dc_vxlans":
                await seed_database_vxlans(v, site)

    # add device data to db
    for device_file in host_var_files:
        device_data_file = open(f"host_vars/{device_file}", "r")
        device_data_dict = yaml.load(device_data_file.read(), Loader=yaml.SafeLoader)
        device_data_file.close()
        await seed_database_devices(device_data_dict)

        # list device under vxlan documents if the vxlan is deployed on the device
        device_vxlans = device_data_dict["vxlans"]
        for vxlan in device_vxlans:
            result = await db["vxlans"].find_one(
                {"name": vxlan, "site": device_data_dict["site"]}
            )
            await db["vxlans"].update_one(
                {"_id": result["_id"]},
                {"$addToSet": {"devices": device_data_dict["hostname"]}},
            )

        device_vrfs = device_data_dict["vxlan_vrfs"]
        for vrf in device_vrfs:
            # result = await db['vrfs'].find_one({'name': vrf})
            await db["vrfs"].update_one(
                {"name": vrf}, {"$addToSet": {"devices": device_data_dict["hostname"]}}
            )

        device_interfaces = device_data_dict["interfaces"]

        # adding interfaces to db
        for interface in device_interfaces:
            _interface = copy.deepcopy(interface)
            for k, v in interface.items():
                if k == "ipv4_address":
                    try:
                        address_split = v.split("/")
                        _interface["ipv4_data"] = {
                            "address": address_split[0],
                            "mask": address_split[1],
                            "IpamSubntID": randint(1, 1000),
                            "type": "unicast",
                        }
                    except:
                        _interface["ipv4_data"] = {
                            "address": None,
                            "mask": None,
                            "IpamSubntID": None,
                            "type": None,
                        }
                elif k == "other":
                    try:
                        _interface["mtu"] = v["mtu"]
                    except KeyError:
                        pass

                elif k == "ipv6_address":
                    _interface["ipv6_data"] = {
                        "address": None,
                        "mask": None,
                        "IpamSubntID": None,
                        "type": None,
                    }
            del _interface["ipv4_address"]
            del _interface["ipv6_address"]
            del _interface["other"]

            _interface["device"] = device_data_dict["hostname"]
            await db["interfaces"].insert_one(_interface)


async def find_vxlans():
    result = await db.vxlans.find().to_list(1000)
    return result


async def testing_list_update():
    update_result = await db["vxlans"].update_one(
        {"_id": ObjectId("6140091d4230136ab9d0329d")},
        {"$addToSet": {"devices": {"$each": ["dev-b", "dev-c"]}}},
    )


if __name__ == "__main__":
    loop.run_until_complete(main())
