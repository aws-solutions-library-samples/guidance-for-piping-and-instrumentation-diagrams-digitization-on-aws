import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, Any, List, Optional
from datetime import datetime
import os


def convert_to_dexpi(graph_data: Dict[str, Any], image_key: str, image_dimensions: Optional[Dict[str, int]] = None) -> str:
    """Convert the graph data to DEXPI XML format.
    
    Args:
        graph_data: Graph data containing 'symbols', 'lines', 'connections', 'junctions', etc.
        image_key: S3 key or filename of the source image
        image_dimensions: Optional image dimensions for coordinate scaling
    
    Returns:
        DEXPI XML string
    """
    
    # Create root element with DEXPI namespace
    root = ET.Element('PlantModel')
    root.set('xmlns', 'http://www.dexpi.org/schema/3.0.0')
    root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    root.set('xsi:schemaLocation', 'http://www.dexpi.org/schema/3.0.0 http://www.dexpi.org/schema/3.0.0/dexpi.xsd')
    
    # Add document metadata
    metadata = ET.SubElement(root, 'DocumentMetaData')
    ET.SubElement(metadata, 'DocumentName').text = os.path.basename(image_key)
    ET.SubElement(metadata, 'DocumentDate').text = datetime.utcnow().isoformat()
    ET.SubElement(metadata, 'DocumentVersion').text = '1.0'
    ET.SubElement(metadata, 'DocumentTool').text = 'AWS P&ID Processing Pipeline'
    
    # Add PlantInformation
    plant_info = ET.SubElement(root, 'PlantInformation')
    ET.SubElement(plant_info, 'PlantName').text = 'Extracted P&ID Data'
    
    # Add statistics if available
    if 'graph_stats' in graph_data:
        stats = graph_data['graph_stats']
        junction_count = stats.get('num_junctions', 0)
        description = f"Nodes: {stats.get('num_nodes', 0)}, Edges: {stats.get('num_edges', 0)}, Components: {stats.get('num_components', 0)}, Junctions: {junction_count}"
        ET.SubElement(plant_info, 'Description').text = description
    
    # Add PlantTopology
    topology = ET.SubElement(root, 'PlantTopology')
    
    # Process symbols and junctions as equipment
    equipment_list = ET.SubElement(topology, 'EquipmentList')
    symbol_id_map = {}
    junction_id_map = {}
    
    # Process symbols first
    for symbol in graph_data.get('symbols', []):
        equipment = create_dexpi_equipment(symbol)
        equipment_list.append(equipment)
        # Map node IDs to DEXPI IDs
        symbol_id_map[f"symbol-{symbol['id']}"] = equipment.get('ID')
    
    # Process junctions as equipment
    for junction in graph_data.get('junctions', []):
        equipment = create_dexpi_junction_equipment(junction)
        equipment_list.append(equipment)
        # Map node IDs to DEXPI IDs
        junction_id_map[f"junction-{junction['id']}"] = equipment.get('ID')
    
    # Process lines as piping network segments
    piping_systems = ET.SubElement(topology, 'PipingNetworkSystemList')
    
    # Group lines into piping systems (simplified - one system for now)
    piping_system = ET.SubElement(piping_systems, 'PipingNetworkSystem')
    piping_system.set('ID', 'PNS-001')
    piping_system.set('TagName', 'Main Piping System')
    
    segments = ET.SubElement(piping_system, 'PipingNetworkSegmentList')
    line_id_map = {}
    
    for line in graph_data.get('lines', []):
        segment = create_dexpi_piping_segment(line, symbol_id_map, graph_data.get('connections', []), junction_id_map)
        segments.append(segment)
        line_id_map[f"line-{line['id']}"] = segment.get('ID')
    
    # Process text elements as annotations
    # Now text is associated with lines, so we extract from there
    annotations = ET.SubElement(topology, 'AnnotationList')
    
    for line in graph_data.get('lines', []):
        if line.get('text_associated'):
            annotation = create_dexpi_annotation_from_line(line, image_dimensions)
            annotations.append(annotation)
    
    # Add connection information as cross-references
    if graph_data.get('connections'):
        cross_refs = ET.SubElement(topology, 'CrossReferenceList')
        for idx, connection in enumerate(graph_data['connections']):
            ref = ET.SubElement(cross_refs, 'CrossReference')
            ref.set('ID', f'XREF-{idx:03d}')
            ref.set('FromID', map_to_dexpi_id(connection['from'], symbol_id_map, line_id_map, junction_id_map))
            ref.set('ToID', map_to_dexpi_id(connection['to'], symbol_id_map, line_id_map, junction_id_map))
    
    # Convert to pretty-printed XML string
    xml_string = prettify_xml(root)
    
    return xml_string


def create_dexpi_equipment(symbol: Dict[str, Any]) -> ET.Element:
    """Create DEXPI equipment element from symbol data."""
    
    equipment = ET.Element('Equipment')
    equipment.set('ID', f'EQ-{symbol["id"]}')
    equipment.set('TagName', symbol.get('type', 'Unknown'))
    
    # Map symbol types to DEXPI equipment types
    equipment_type_map = {
        'pump': 'CentrifugalPump',
        'valve': 'GateValve',
        'tank': 'StorageTank',
        'vessel': 'PressureVessel',
        'heat_exchanger': 'ShellAndTubeHeatExchanger',
        'heat exchanger': 'ShellAndTubeHeatExchanger',
        'compressor': 'CentrifugalCompressor',
        'instrument': 'Instrument',
        'flow_meter': 'FlowMeter',
        'pressure_indicator': 'PressureIndicator',
        'temperature_indicator': 'TemperatureIndicator',
        'control_valve': 'ControlValve',
        'unknown': 'GenericEquipment'
    }
    
    # Get equipment type from mapping
    symbol_type = symbol.get('type', 'unknown').lower().replace('-', '_')
    equipment_type = equipment_type_map.get(symbol_type, 'GenericEquipment')
    
    ET.SubElement(equipment, 'EquipmentType').text = equipment_type
    
    # Add position information (center of bounding box)
    bbox = symbol.get('bbox', [0, 0, 0, 0])
    position = ET.SubElement(equipment, 'Position')
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    ET.SubElement(position, 'X').text = str(center_x)
    ET.SubElement(position, 'Y').text = str(center_y)
    
    # Add bounding box
    extent = ET.SubElement(equipment, 'Extent')
    min_point = ET.SubElement(extent, 'Min')
    min_point.set('X', str(bbox[0]))
    min_point.set('Y', str(bbox[1]))
    max_point = ET.SubElement(extent, 'Max')
    max_point.set('X', str(bbox[2]))
    max_point.set('Y', str(bbox[3]))
    
    # Add connections if available
    if symbol.get('connections'):
        conn_list = ET.SubElement(equipment, 'NozzleList')
        for idx, conn_id in enumerate(symbol['connections']):
            nozzle = ET.SubElement(conn_list, 'Nozzle')
            nozzle.set('ID', f'N-{symbol["id"]}-{idx:02d}')
            nozzle.set('ConnectedToID', conn_id)
    
    return equipment


def create_dexpi_junction_equipment(junction: Dict[str, Any]) -> ET.Element:
    """Create DEXPI equipment element from junction data."""
    
    equipment = ET.Element('Equipment')
    equipment.set('ID', f'JUN-{junction["id"]}')
    
    # Map junction types to DEXPI equipment types and tag names
    junction_type_map = {
        't_junction': {'type': 'Tee', 'tag': 'Tee Junction'},
        'l_junction': {'type': 'Elbow', 'tag': 'Elbow Junction'},
        'cross_junction': {'type': 'Cross', 'tag': 'Cross Junction'},
        'unknown': {'type': 'PipingComponent', 'tag': 'Unknown Junction'}
    }
    
    junction_type = junction.get('junction_type', 'unknown').lower()
    mapping = junction_type_map.get(junction_type, junction_type_map['unknown'])
    
    equipment.set('TagName', f"{mapping['tag']}-{junction['id']}")
    ET.SubElement(equipment, 'EquipmentType').text = mapping['type']
    
    # Add position information from junction point
    point = junction.get('point', [0, 0])
    position = ET.SubElement(equipment, 'Position')
    ET.SubElement(position, 'X').text = str(point[0])
    ET.SubElement(position, 'Y').text = str(point[1])
    
    # Add minimal extent around the junction point (small radius for point-like junction)
    extent_radius = 5.0  # Small radius for junction representation
    extent = ET.SubElement(equipment, 'Extent')
    min_point = ET.SubElement(extent, 'Min')
    min_point.set('X', str(point[0] - extent_radius))
    min_point.set('Y', str(point[1] - extent_radius))
    max_point = ET.SubElement(extent, 'Max')
    max_point.set('X', str(point[0] + extent_radius))
    max_point.set('Y', str(point[1] + extent_radius))
    
    # Add nozzles for connected lines
    connected_lines = junction.get('connected_lines', [])
    if connected_lines:
        conn_list = ET.SubElement(equipment, 'NozzleList')
        for idx, line_id in enumerate(connected_lines):
            nozzle = ET.SubElement(conn_list, 'Nozzle')
            nozzle.set('ID', f'N-JUN-{junction["id"]}-{idx:02d}')
            nozzle.set('ConnectedToID', f'PNS-{line_id}')
            
            # Add nozzle position (same as junction point for now)
            nozzle_pos = ET.SubElement(nozzle, 'Position')
            ET.SubElement(nozzle_pos, 'X').text = str(point[0])
            ET.SubElement(nozzle_pos, 'Y').text = str(point[1])
    
    # Add metadata
    if junction.get('confidence'):
        metadata = ET.SubElement(equipment, 'GenericAttributes')
        attr = ET.SubElement(metadata, 'GenericAttribute')
        attr.set('Name', 'DetectionConfidence')
        attr.set('Value', str(junction['confidence']))
        attr.set('Format', 'Double')
    
    return equipment


def create_dexpi_piping_segment(line: Dict[str, Any], 
                               symbol_id_map: Dict[str, str],
                               connections: List[Dict[str, str]],
                               junction_id_map: Dict[str, str] = None) -> ET.Element:
    """Create DEXPI piping segment from line data."""
    
    segment = ET.Element('PipingNetworkSegment')
    segment.set('ID', f'PNS-{line["id"]}')
    
    # Add text association as tag if available
    if line.get('text_associated'):
        segment.set('TagName', line['text_associated'])
    
    # Add centerline from points
    centerline = ET.SubElement(segment, 'CenterLine')
    
    points = line.get('points', [])
    for point in points:
        pt = ET.SubElement(centerline, 'Point')
        pt.set('X', str(point[0]))
        pt.set('Y', str(point[1]))
    
    # Add connections to equipment (symbols and junctions)
    line_node_id = f"line-{line['id']}"
    connected_components = []
    
    # Find connections from the connections list (symbols and junctions)
    for conn in connections:
        if conn['from'] == line_node_id:
            if conn['to'].startswith('symbol-') or conn['to'].startswith('junction-'):
                connected_components.append(conn['to'])
        elif conn['to'] == line_node_id:
            if conn['from'].startswith('symbol-') or conn['from'].startswith('junction-'):
                connected_components.append(conn['from'])
    
    # Also check the line's own connections list if available
    if line.get('connections'):
        for conn_id in line['connections']:
            if (conn_id.startswith('symbol-') or conn_id.startswith('junction-')) and conn_id not in connected_components:
                connected_components.append(conn_id)
    
    if connected_components:
        conn_list = ET.SubElement(segment, 'ConnectionList')
        for component_node_id in connected_components:
            dexpi_id = None
            
            # Map to appropriate DEXPI ID
            if component_node_id in symbol_id_map:
                dexpi_id = symbol_id_map[component_node_id]
            elif junction_id_map and component_node_id in junction_id_map:
                dexpi_id = junction_id_map[component_node_id]
            
            if dexpi_id:
                connection = ET.SubElement(conn_list, 'Connection')
                connection.set('ToComponentID', dexpi_id)
    
    # Add flow direction if determinable from connections
    if len(connected_components) >= 2:
        flow = ET.SubElement(segment, 'FlowDirection')
        from_id = None
        to_id = None
        
        # Get DEXPI IDs for flow direction
        if connected_components[0] in symbol_id_map:
            from_id = symbol_id_map[connected_components[0]]
        elif junction_id_map and connected_components[0] in junction_id_map:
            from_id = junction_id_map[connected_components[0]]
            
        if connected_components[1] in symbol_id_map:
            to_id = symbol_id_map[connected_components[1]]
        elif junction_id_map and connected_components[1] in junction_id_map:
            to_id = junction_id_map[connected_components[1]]
        
        flow.set('From', from_id or 'Unknown')
        flow.set('To', to_id or 'Unknown')
    
    return segment


def create_dexpi_annotation_from_line(line: Dict[str, Any], 
                                     image_dimensions: Optional[Dict[str, int]] = None) -> ET.Element:
    """Create DEXPI annotation from line's associated text."""
    
    annotation = ET.Element('Annotation')
    annotation.set('ID', f'AN-LINE-{line["id"]}')
    
    # Set text content
    text = line['text_associated']
    ET.SubElement(annotation, 'Text').text = text
    
    # Classify annotation type based on text pattern
    if any(char in text for char in ['"', "'"]):  # Pipe size indicators
        annotation.set('Type', 'PipeSize')
    elif '-' in text and any(char.isdigit() for char in text):  # Tag numbers
        annotation.set('Type', 'TagNumber')
    elif any(unit in text.lower() for unit in ['gpm', 'psi', '°f', '°c', 'bar']):
        annotation.set('Type', 'ProcessData')
    else:
        annotation.set('Type', 'General')
    
    # Position annotation at the midpoint of the line
    points = line.get('points', [])
    if points:
        mid_idx = len(points) // 2
        mid_point = points[mid_idx]
        
        position = ET.SubElement(annotation, 'Position')
        ET.SubElement(position, 'X').text = str(mid_point[0])
        ET.SubElement(position, 'Y').text = str(mid_point[1])
    
    # Associate with the line
    ET.SubElement(annotation, 'AssociatedComponentID').text = f'PNS-{line["id"]}'
    
    return annotation


def map_to_dexpi_id(node_id: str, symbol_id_map: Dict[str, str], line_id_map: Dict[str, str], junction_id_map: Dict[str, str] = None) -> str:
    """Map internal node ID to DEXPI component ID."""
    if node_id in symbol_id_map:
        return symbol_id_map[node_id]
    elif node_id in line_id_map:
        return line_id_map[node_id]
    elif junction_id_map and node_id in junction_id_map:
        return junction_id_map[node_id]
    else:
        # Handle virtual lines or unknown IDs
        if 'virtual' in node_id:
            return f'VIRT-{node_id}'
        return f'UNK-{node_id}'


def prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")
