import ipaddress

# checks for both standard IP address, and CIDR notation
def valid_ip_interface(address):
    try:
        ipaddress.ip_interface(address)
    except ValueError:
        return False
    return True

# checks for standard IP address
def valid_ip_address(address):
    try:
        ipaddress.ip_interface(address)
    except ValueError:
        return False
    return True
