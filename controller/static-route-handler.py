import kopf
from pyroute2 import IPRoute
from api.v1.types import StaticRoute
from constants import DEFAULT_GW_CIDR
from constants import NODE_HOSTNAME
from constants import NOT_USABLE_IP_ADDRESS
from constants import ROUTE_EVT_MSG
from constants import ROUTE_READY_MSG
from constants import ROUTE_NOT_READY_MSG
from utils import valid_ip_address, valid_ip_interface


# =================================== Static route management ===========================================
#
# Works the same way as the Linux `ip route` command:
#  - "add":     Adds a new entry in the Linux routing table (must not exist beforehand)
#  - "change":  Changes an entry from the the Linux routing table (must exist beforehand)
#  - "delete":  Deletes an entry from the Linux routing table (must exist beforehand)
#  - "replace": Replaces an entry from the Linux routing table if it exists, creates a new one otherwise
#
# =======================================================================================================


def manage_static_route(operation, destination, gateway, interface, logger=None, override_bad_destination=False):
    operation_success = False
    message = ""

    # Check if destination/gateway IP address/CIDR is valid first
    if not valid_ip_interface(destination) or not valid_ip_address(gateway):
        message = f"Invalid IP address specified for route - dest: {destination}, gateway: {gateway}!"
        if logger is not None:
            logger.error(message)
        return (False, message)

    # We don't want to mess with default GW settings, or with the '0.0.0.0' IP address
    if not override_bad_destination and (destination == DEFAULT_GW_CIDR or destination == NOT_USABLE_IP_ADDRESS):
        message = f"Route {operation} request denied - dest: {destination}, gateway: {gateway}!"
        if logger is not None:
            logger.error(message)
        return (False, message)

    with IPRoute() as ipr:
        try:
            if interface is None:
                ipr.route(
                    operation,
                    dst=destination,
                    gateway=gateway,
                )
            else:
                ipr.route(
                    operation,
                    dst=destination,
                    gateway=gateway,
                    oif=ipr.link_lookup(ifname=interface)[0],
                )
            operation_success = True
            message = f"Success - Dest: {destination}, gateway: {gateway}, operation: {operation}."
            if logger is not None:
                logger.info(message)
        except Exception as ex:
            operation_success = False
            message = f"Route {operation} failed! Error message: {ex}"
            if logger is not None:
                logger.error(message)

    return (operation_success, message)


def process_static_routes(routes, operation, event_ctx=None, logger=None):
    status = []

    for route in routes:
        operation_succeeded, message = manage_static_route(
            operation=operation,
            destination=route.get("destination"),
            gateway=route.get("gateway"),
            interface=route.get("interface"),
            override_bad_destination=route.get("override_bad_destination"),
            logger=logger,
        )

        if not operation_succeeded:
            status.append(
                {
                    "destination": route.get("destination"),
                    "gateway": route.get("gateway"),
                    "interface": route.get("interface"),
                    "status": ROUTE_NOT_READY_MSG,
                }
            )
            if event_ctx is not None:
                kopf.exception(
                    event_ctx,
                    reason=ROUTE_EVT_MSG[operation]["failure"],
                    message=message,
                )
            continue

        status.append(
            {
                "destination": route.get("destination"),
                "gateway": route.get("gateway"),
                "interface": route.get("interface"),
                "status": ROUTE_READY_MSG,
            }
        )
        if event_ctx is not None:
            kopf.info(
                event_ctx, reason=ROUTE_EVT_MSG[operation]["success"], message=message
            )

    return status


# ============================== Create Handler =====================================
#
# Default behavior is to "add" the static route(s) specified in our CRD
# If the static route already exists, it will not be overwritten.
#
# ===================================================================================


@kopf.on.resume(StaticRoute.__group__, StaticRoute.__version__, StaticRoute.__name__)
@kopf.on.create(StaticRoute.__group__, StaticRoute.__version__, StaticRoute.__name__)
def create_fn(body, spec, logger, **_):
    nodeName = spec.get("nodeName")
    if nodeName is not None and nodeName != NODE_HOSTNAME:
        return
        
    destinations = spec.get("destinations", [])
    gateway = spec.get("gateway")
    interface = spec.get("interface")
    override_bad_destination = spec.get("force")
    replace = spec.get("replace")
    remove = spec.get("remove")

    routes_to_add_spec = [
            {"destination": destination, "gateway": gateway, "interface": interface, "override_bad_destination": override_bad_destination} for destination in destinations
    ]

    operation = "add"
    if remove:
        operation = "del"
    elif replace:
        operation = "replace"

    return process_static_routes(
        routes=routes_to_add_spec, operation=operation, event_ctx=body, logger=logger
    )


# ============================== Update Handler =====================================
#
# Default behavior is to update/replace the static route(s) specified in our CRD
#
# ===================================================================================


@kopf.on.update(StaticRoute.__group__, StaticRoute.__version__, StaticRoute.__name__)
def update_fn(body, old, new, logger, **_):
    oldNodeName = old["spec"].get("nodeName")
    newNodeName = new["spec"].get("nodeName")

    old_gateway = old["spec"].get("gateway")
    new_gateway = new["spec"].get("gateway")
    old_destinations = old["spec"].get("destinations", [])
    new_destinations = new["spec"].get("destinations", [])
    old_interface = old["spec"].get("interface")
    new_interface = new["spec"].get("interface")
    old_remove = old["spec"].get("remove")
    new_remove = new["spec"].get("remove")
    old_replace = old["spec"].get("replace")
    new_replace = new["spec"].get("replace")
    old_override_bad_destination = old["spec"].get("force")
    new_override_bad_destination = new["spec"].get("force")
    destinations_to_delete = list(set(old_destinations) - set(new_destinations))
    destinations_to_add = list(set(new_destinations) - set(old_destinations))

    if oldNodeName is None or oldNodeName == NODE_HOSTNAME:
        routes_to_delete_spec = [
            {"destination": destination, "gateway": old_gateway, "interface": old_interface, "override_bad_destination": old_override_bad_destination}
            for destination in destinations_to_delete
        ]
        operation = "del"
        if old_remove:
            operation = "add"
        elif old_replace:
            operation = "del"
        process_static_routes(
            routes=routes_to_delete_spec, operation=operation, event_ctx=body, logger=logger
        )

    if newNodeName is None or newNodeName == NODE_HOSTNAME:
        routes_to_add_spec = [
            {"destination": destination, "gateway": new_gateway, "interface": new_interface, "override_bad_destination": new_override_bad_destination}
            for destination in destinations_to_add
        ]
        operation = "add"
        if new_remove:
            operation = "del"
        elif new_replace:
            operation = "replace"
        process_static_routes(
            routes=routes_to_add_spec, operation=operation, event_ctx=body, logger=logger
        )

    return


# ============================== Delete Handler =====================================
#
# Default behavior is to delete the static route(s) specified in our CRD only!
#
# ===================================================================================


@kopf.on.delete(StaticRoute.__group__, StaticRoute.__version__, StaticRoute.__name__)
def delete(body, spec, logger, **_):
    nodeName = spec.get("nodeName")
    if nodeName is not None and nodeName != NODE_HOSTNAME:
        return

    destinations = spec.get("destinations", [])
    gateway = spec.get("gateway")
    interface = spec.get("interface")
    override_bad_destination = spec.get("force")
    remove = spec.get("remove")
    replace = spec.get("replace")

    routes_to_delete_spec = [
            {"destination": destination, "gateway": gateway, "interface": interface, "override_bad_destination": override_bad_destination} for destination in destinations
    ]

    operation = "del"
    if remove:
        operation = "add"
    elif replace:
        operation = "del"

    return process_static_routes(
        routes=routes_to_delete_spec, operation=operation, event_ctx=body, logger=logger
    )
