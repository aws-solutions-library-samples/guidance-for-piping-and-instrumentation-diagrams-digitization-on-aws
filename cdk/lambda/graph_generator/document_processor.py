"""
Main document processor that orchestrates P&ID graph processing using modular components.
"""

import logging
from typing import Dict, List, Any, Optional
from models import (
    BoundingBox, Symbol, LineSegment, TextElement, ConnectionCandidate, GraphNodeType
)
from graph_service import GraphService
from geometry import calculate_line_to_bbox_distance, calculate_line_to_line_distance, calculate_bbox_distance, calculate_enhanced_line_to_bbox_distance
from line_processor import LineProcessor
from text_associator import TextAssociator
from junction_detector import JunctionDetector

logger = logging.getLogger()


class DocumentProcessor:
    """Process P&ID documents and extract graph structure"""
    
    def __init__(self, config: Dict):
        if not config:
            raise ValueError("Config is required - should be provided from index.py")
        self.config = config
        self.graph_service = GraphService()
        self.line_processor = LineProcessor(self.graph_service, self.config)
        self.text_associator = TextAssociator(self.graph_service, self.config)
        self.junction_detector = JunctionDetector(self.config)
        self.virtual_line_counter = 1000  # Start at 1000 to avoid conflicts with regular lines
    
    def process_document(self, file_path: str, 
                        symbols: List[Dict], 
                        lines: List[Dict], 
                        texts: List[Dict],
                        original_text_elements: List[Dict] = None) -> Dict[str, Any]:
        """
        Process a P&ID document and extract symbols, lines, and text with proper associations
        """
        if original_text_elements is None:
            original_text_elements = []
        
        # Store original text elements for final output
        self.original_text_elements = original_text_elements
        
        # Convert input data to internal structures
        symbol_objects = [self._dict_to_symbol(s) for s in symbols]
        line_objects = [self._dict_to_line(l) for l in lines]
        text_objects = [self._dict_to_text(t) for t in texts]
        
        # Initialize graph with nodes
        self._initialize_graph(symbol_objects, line_objects)
        
        # Create line connection candidates (lines and text only, skip symbols initially)
        line_connection_candidates = self._create_line_connection_candidates(
            line_objects, text_objects
        )
        
        # Connect lines with closest elements and track associated text
        associated_text_ids = self._connect_lines_with_closest_elements(
            line_connection_candidates, text_objects
        )
        
        # PHASED MERGING WITH T-JUNCTION PROTECTION
        logger.info("Starting phased line merging with T-junction protection...")
        
        # Phase A: Safe merging (aberrant + geometric only)
        logger.info("Phase A: Safe merging (aberrant + geometric)")
        self.line_processor.merge_lines_safely_iteratively()
        
        # Phase B: Detect T-junctions for protection
        logger.info("Phase B: Detecting T-junctions for protection")
        intermediate_line_objects = self._get_updated_line_objects()
        protection_junctions = self.junction_detector.detect_junctions(intermediate_line_objects)
        logger.info(f"Found {len(protection_junctions)} junctions to protect from L-shape merging")
        
        # Phase C: L-shape merging with T-junction protection
        logger.info("Phase C: L-shape merging with T-junction protection")
        
        # Separate L-junctions for merging from T-junctions for protection
        l_junctions = [j for j in protection_junctions if j.junction_type.value == 'l_junction']
        t_junctions = [j for j in protection_junctions if j.junction_type.value == 't_junction']
        
        logger.info(f"Found {len(l_junctions)} L-junctions to merge and {len(t_junctions)} T-junctions to protect")
        
        self.line_processor.merge_l_shapes_with_protection_iteratively(l_junctions, t_junctions)
        
        # Phase D: Final junction detection on consolidated lines
        logger.info("Phase D: Final junction detection")
        updated_line_objects = self._get_updated_line_objects()
        detected_junctions = self.junction_detector.detect_junctions(updated_line_objects)
        logger.info(f"Detected {len(detected_junctions)} final junctions")
        
        # Add junction nodes to the graph
        for junction in detected_junctions:
            junction_id = self.graph_service.add_junction_node(junction)
            self.graph_service.connect_lines_through_junction(junction)
            logger.info(f"Added junction {junction_id} ({junction.junction_type.value}) connecting lines: {junction.connected_lines}")
        
        # Now connect symbols to the final merged lines
        self._connect_symbols_to_merged_lines(symbol_objects)
        
        # Associate remaining text with symbols
        self.text_associator.associate_text_with_symbols(symbol_objects, text_objects, associated_text_ids)
        
        # Connect symbols that are close (for symbols without line connections)
        self._connect_symbols_that_are_close(symbol_objects)
        
        # Phase E: Graph-based component filtering to remove frames, notes, and isolated artifacts
        logger.info("Phase E: Graph-based component filtering")
        self._filter_unwanted_components()
        
        # Build final output including standalone text
        return self._build_output(text_objects, associated_text_ids, symbol_objects)
    
    def _dict_to_symbol(self, data: Dict) -> Symbol:
        """Convert dictionary to Symbol object"""
        bbox = BoundingBox(
            topX=data["bbox"]['x1'],
            topY=data["bbox"]['y1'],
            bottomX=data["bbox"]['x2'],
            bottomY=data["bbox"]['y2']
        )
        return Symbol(
            id=data["id"],
            label=data.get("type", "unknown"),
            class_name=data.get("class_name", "unknown"),
            bbox=bbox,
            score=data.get("score", 0.9)
        )
    
    def _dict_to_line(self, data: Dict) -> LineSegment:
        """Convert dictionary to LineSegment object"""
        return LineSegment(
            id=data["id"],
            points=data["points"]
        )
    
    def _dict_to_text(self, data: Dict) -> TextElement:
        """Convert dictionary to TextElement object"""
        bbox = BoundingBox(
            topX=data["bbox"][0],
            topY=data["bbox"][1],
            bottomX=data["bbox"][2],
            bottomY=data["bbox"][3]
        )
        return TextElement(
            id=data["id"],
            text=data["text"],
            bbox=bbox,
            score=data.get("score", 0.9)
        )
    
    def _initialize_graph(self, symbols: List[Symbol], lines: List[LineSegment]):
        """Initialize graph with symbol and line nodes"""
        # Add symbol nodes
        for symbol in symbols:
            node_id = f"symbol-{symbol.id}"
            self.graph_service.add_node(
                node_id,
                GraphNodeType.SYMBOL,
                label=symbol.label,
                class_name=symbol.class_name,
                bbox=symbol.bbox,
                score=symbol.score
            )
        
        # Add line nodes
        for line in lines:
            node_id = f"line-{line.id}"
            self.graph_service.add_node(
                node_id,
                GraphNodeType.LINE,
                points=line.points
            )
    
    def _create_line_connection_candidates(self, 
                                         lines: List[LineSegment],
                                         texts: List[TextElement]) -> Dict[str, List[ConnectionCandidate]]:
        """Create connection candidates for each line (excluding symbols, handled later)"""
        candidates = {}
        
        for line in lines:
            line_id = f"line-{line.id}"
            line_candidates = []
            
            # Find texts close to line
            for text in texts:
                distance = calculate_line_to_bbox_distance(line.points, text.bbox)
                if distance <= self.config["graph_distance_threshold_for_text"]:
                    line_candidates.append(ConnectionCandidate(
                        node_type=GraphNodeType.TEXT,
                        element_id=text.id,
                        distance=distance
                    ))
            
            # Find other lines close to this line
            for other_line in lines:
                if other_line.id != line.id:
                    distance = calculate_line_to_line_distance(line.points, other_line.points)
                    if distance <= self.config["graph_distance_threshold_for_lines"]:
                        line_candidates.append(ConnectionCandidate(
                            node_type=GraphNodeType.LINE,
                            element_id=other_line.id,
                            distance=distance
                        ))
            
            candidates[line_id] = line_candidates
        
        return candidates
    
    def _connect_lines_with_closest_elements(self,
                                           line_connection_candidates: Dict[str, List[ConnectionCandidate]],
                                           text_elements: List[TextElement]) -> set:
        """Connect lines with their closest elements and return set of associated text IDs"""
        associated_text_ids = set()
        
        for line_node_id, candidates in line_connection_candidates.items():
            for candidate in candidates:
                if candidate.node_type == GraphNodeType.TEXT:
                    # Associate text with line
                    text_elem = next((t for t in text_elements if t.id == candidate.element_id), None)
                    if text_elem:
                        line_node = self.graph_service.get_node(line_node_id)
                        line_node['text_associated'] = text_elem.text
                        associated_text_ids.add(candidate.element_id)
                        
                elif candidate.node_type == GraphNodeType.LINE:
                    # Connect line to line
                    other_line_id = f"line-{candidate.element_id}"
                    self.graph_service.add_edge(line_node_id, other_line_id)
        
        return associated_text_ids
    
    def _get_updated_line_objects(self) -> List[LineSegment]:
        """Get updated line objects from the graph after aberrant merging"""
        updated_lines = []
        
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                # Extract line ID from node_id (remove 'line-' prefix)
                line_id = node_id.replace('line-', '')
                
                # Create LineSegment object
                line_segment = LineSegment(
                    id=line_id,
                    points=data['points']
                )
                
                updated_lines.append(line_segment)
        
        logger.info(f"Retrieved {len(updated_lines)} updated line objects from graph")
        return updated_lines
    
    def _connect_symbols_to_merged_lines(self, symbols: List[Symbol]):
        """Connect symbols to lines after line consolidation using enhanced distance calculation"""
        # Get all line nodes from the graph
        line_nodes = {}
        merged_lines = set()
        
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                line_nodes[node_id] = data['points']
                # Track merged lines - their connections were handled selectively during merging
                if data.get('merged_from') or 'l-junction' in node_id:
                    merged_lines.add(node_id)
        
        # For each symbol, check distance to all lines using enhanced distance calculation
        for symbol in symbols:
            symbol_id = f"symbol-{symbol.id}"
            
            for line_node_id, line_points in line_nodes.items():
                # For merged lines, prioritize selective connections but allow distance-based ones
                if line_node_id in merged_lines:
                    if self.graph_service.graph.has_edge(symbol_id, line_node_id):
                        logger.info(f"Keeping existing selective connection: {symbol_id} <-> {line_node_id}")
                        continue
                    else:
                        # No selective connection exists, check if distance-based connection is appropriate
                        distance = calculate_enhanced_line_to_bbox_distance(line_points, symbol.bbox)
                        # Use a very restrictive threshold for merged lines to avoid inappropriate connections
                        merged_line_threshold = self.config["graph_distance_threshold_for_symbols"] * 0.2
                        
                        if distance <= merged_line_threshold:
                            self.graph_service.add_edge(symbol_id, line_node_id)
                            logger.info(f"Connected {symbol_id} to merged line {line_node_id} (enhanced distance: {distance:.2f})")
                        continue
                
                # For regular (non-merged) lines, connect based on distance
                distance = calculate_enhanced_line_to_bbox_distance(line_points, symbol.bbox)
                
                if distance <= self.config["graph_distance_threshold_for_symbols"]:
                    # Connect symbol to line
                    self.graph_service.add_edge(symbol_id, line_node_id)
                    logger.info(f"Connected {symbol_id} to {line_node_id} (enhanced distance: {distance:.2f})")
    
    def _connect_symbols_that_are_close(self, symbols: List[Symbol]):
        """Connect symbols that are close to each other"""
        for i, symbol1 in enumerate(symbols):
            symbol1_id = f"symbol-{symbol1.id}"
            
            # Check if symbol needs more connections
            if self.graph_service.get_degree(symbol1_id) < 2:
                for j, symbol2 in enumerate(symbols):
                    if i != j:
                        distance = calculate_bbox_distance(symbol1.bbox, symbol2.bbox)
                        if distance <= self.config["graph_symbol_to_symbol_distance_threshold"]:
                            symbol2_id = f"symbol-{symbol2.id}"
                            
                            # Create a virtual line between symbols with simple ID
                            self.virtual_line_counter += 1
                            virtual_line_id = f"line-{self.virtual_line_counter}"
                            self.graph_service.add_node(
                                virtual_line_id,
                                GraphNodeType.LINE,
                                points=[symbol1.bbox.center(), symbol2.bbox.center()],
                                virtual=True
                            )
                            
                            # Connect symbols through virtual line
                            self.graph_service.add_edge(symbol1_id, virtual_line_id)
                            self.graph_service.add_edge(virtual_line_id, symbol2_id)
    
    def _filter_unwanted_components(self):
        """
        Filter out unwanted connected components (frames, notes, isolated artifacts)
        based on graph structure analysis
        """
        # Get configuration parameters with defaults
        filter_enabled = self.config.get("component_filter_enabled", True)
        min_component_size = self.config.get("min_component_size", 3)
        max_line_density = self.config.get("max_line_density", 0.9)
        min_symbol_density = self.config.get("min_symbol_density", 0.1)
        max_notes_component_size = self.config.get("max_notes_component_size", 15)
        frame_aspect_ratio_threshold = self.config.get("frame_aspect_ratio_threshold", 0.1)
        max_symbol_density_for_removal = self.config.get("max_symbol_density_for_removal", 0.1)
        extreme_symbol_density_threshold = self.config.get("extreme_symbol_density_threshold", 0.05)
        
        # Log configuration values for debugging
        logger.info(f"=== COMPONENT FILTERING CONFIG ===")
        logger.info(f"filter_enabled: {filter_enabled}")
        logger.info(f"min_component_size: {min_component_size}")
        logger.info(f"max_symbol_density_for_removal: {max_symbol_density_for_removal}")
        logger.info(f"extreme_symbol_density_threshold: {extreme_symbol_density_threshold}")
        logger.info(f"max_line_density: {max_line_density}")
        logger.info(f"min_symbol_density: {min_symbol_density}")
        
        if not filter_enabled:
            logger.info("Component filtering disabled")
            return
        
        # Get all connected components
        components = self.graph_service.get_connected_components()
        original_component_count = len(components)
        
        logger.info(f"=== ANALYZING {original_component_count} CONNECTED COMPONENTS ===")
        
        nodes_to_remove = []
        components_removed = 0
        
        for i, component in enumerate(components):
            component_nodes = list(component)
            component_size = len(component_nodes)
            
            # Analyze component composition
            analysis = self._analyze_component(component_nodes)
            
            # Log detailed analysis for each component (especially large ones)
            if component_size > 100:  # Focus on large components
                logger.info(f"--- LARGE COMPONENT {i+1} ANALYSIS ---")
                logger.info(f"Component size: {component_size} nodes")
                logger.info(f"Symbol count: {analysis['symbol_count']} (density: {analysis['symbol_density']:.4f})")
                logger.info(f"Line count: {analysis['line_count']} (density: {analysis['line_density']:.4f})")
                logger.info(f"Junction count: {analysis['junction_count']} (density: {analysis['junction_density']:.4f})")
                logger.info(f"Text count: {analysis['text_count']} (density: {analysis['text_density']:.4f})")
                
                # Show some sample node IDs for identification
                sample_nodes = component_nodes[:10] if len(component_nodes) > 10 else component_nodes
                logger.info(f"Sample nodes: {sample_nodes}")
            
            # Decision logic for removing components
            should_remove = False
            removal_reason = ""
            
            # Rule 1: Very small isolated components
            if component_size < min_component_size:
                should_remove = True
                removal_reason = f"Rule 1: too small ({component_size} nodes)"
                if component_size > 100:
                    logger.info(f"Rule 1 evaluation: {component_size} < {min_component_size} = {should_remove}")
            
            # Rule 2: Line-heavy components with few symbols (improved with conditional size protection)
            elif (analysis['symbol_density'] < max_symbol_density_for_removal and  # Less than 10% symbols
                  (component_size < 50 or analysis['symbol_density'] < extreme_symbol_density_threshold) and  # Size protection OR extremely low symbols
                  analysis['line_count'] > 0):          # Has lines
                should_remove = True
                size_bypass = analysis['symbol_density'] < extreme_symbol_density_threshold
                removal_reason = f"Rule 2: line-heavy with few symbols (symbol_density: {analysis['symbol_density']:.4f}, lines: {analysis['line_count']}, size_bypass: {size_bypass})"
                if component_size > 100:
                    logger.info(f"Rule 2 evaluation:")
                    logger.info(f"  symbol_density < max_symbol_density_for_removal: {analysis['symbol_density']:.4f} < {max_symbol_density_for_removal} = {analysis['symbol_density'] < max_symbol_density_for_removal}")
                    logger.info(f"  size condition: (component_size < 50 OR symbol_density < extreme_threshold)")
                    logger.info(f"    component_size < 50: {component_size} < 50 = {component_size < 50}")
                    logger.info(f"    symbol_density < extreme_threshold: {analysis['symbol_density']:.4f} < {extreme_symbol_density_threshold} = {analysis['symbol_density'] < extreme_symbol_density_threshold}")
                    logger.info(f"    size condition result: {component_size < 50 or analysis['symbol_density'] < extreme_symbol_density_threshold}")
                    logger.info(f"  line_count > 0: {analysis['line_count']} > 0 = {analysis['line_count'] > 0}")
                    logger.info(f"  Final Rule 2 result: {should_remove}")
            
            # Rule 3: Frame detection - high line density with low symbol density (original rule, more restrictive)
            elif (analysis['line_density'] > max_line_density and 
                  analysis['symbol_density'] < min_symbol_density and
                  self._is_frame_like_geometry(component_nodes, analysis)):
                should_remove = True
                removal_reason = f"Rule 3: frame pattern (line_density: {analysis['line_density']:.4f}, symbol_density: {analysis['symbol_density']:.4f})"
                if component_size > 100:
                    logger.info(f"Rule 3 evaluation: line_density > {max_line_density} AND symbol_density < {min_symbol_density} AND frame_geometry = {should_remove}")
            
            # Rule 4: Notes/legend detection - high text density with few symbols
            elif (component_size <= max_notes_component_size and
                  analysis['text_density'] > 0.4 and 
                  analysis['symbol_density'] < min_symbol_density):
                should_remove = True
                removal_reason = f"Rule 4: notes/legend pattern (text_density: {analysis['text_density']:.4f}, symbol_density: {analysis['symbol_density']:.4f})"
                if component_size > 100:
                    logger.info(f"Rule 4 evaluation: size <= {max_notes_component_size} AND text_density > 0.4 AND symbol_density < {min_symbol_density} = {should_remove}")
            
            # Rule 5: Isolated line segments (only lines, no symbols or junctions)
            elif (analysis['symbol_count'] == 0 and 
                  analysis['junction_count'] == 0 and 
                  analysis['line_count'] > 0 and
                  component_size < 10):  # Small isolated line groups
                should_remove = True
                removal_reason = f"Rule 5: isolated lines ({analysis['line_count']} lines, no symbols/junctions)"
                if component_size > 100:
                    logger.info(f"Rule 5 evaluation: symbols=0 AND junctions=0 AND lines>0 AND size<10 = {should_remove}")
            
            if should_remove:
                logger.info(f"REMOVING component {i+1} with {component_size} nodes: {removal_reason}")
                nodes_to_remove.extend(component_nodes)
                components_removed += 1
            else:
                if component_size > 100:
                    logger.info(f"KEEPING large component {i+1} with {component_size} nodes - no removal rules matched")
                else:
                    logger.info(f"Keeping component {i+1} with {component_size} nodes (symbols: {analysis['symbol_count']}, lines: {analysis['line_count']})")
        
        # Remove identified nodes from the graph
        if nodes_to_remove:
            self.graph_service.remove_nodes(nodes_to_remove)
            logger.info(f"Component filtering complete: removed {components_removed} components ({len(nodes_to_remove)} nodes)")
        else:
            logger.info("Component filtering complete: no components removed")
        
        # Store filtering statistics for output
        self.component_filtering_stats = {
            'filter_enabled': filter_enabled,
            'original_component_count': original_component_count,
            'components_removed': components_removed,
            'nodes_removed': len(nodes_to_remove),
            'final_component_count': len(self.graph_service.get_connected_components())
        }
    
    def _analyze_component(self, component_nodes: List[str]) -> Dict[str, Any]:
        """Analyze the composition of a connected component"""
        symbol_count = 0
        line_count = 0
        junction_count = 0
        text_count = 0  # Nodes with associated text
        
        for node_id in component_nodes:
            if not self.graph_service.graph.has_node(node_id):
                continue
                
            node_data = self.graph_service.get_node(node_id)
            node_type = node_data.get('node_type')
            
            if node_type == GraphNodeType.SYMBOL:
                symbol_count += 1
            elif node_type == GraphNodeType.LINE:
                line_count += 1
                # Check if line has associated text
                if node_data.get('text_associated'):
                    text_count += 1
            elif node_type == GraphNodeType.JUNCTION:
                junction_count += 1
        
        total_nodes = len(component_nodes)
        
        return {
            'symbol_count': symbol_count,
            'line_count': line_count,
            'junction_count': junction_count,
            'text_count': text_count,
            'total_nodes': total_nodes,
            'symbol_density': symbol_count / total_nodes if total_nodes > 0 else 0,
            'line_density': line_count / total_nodes if total_nodes > 0 else 0,
            'junction_density': junction_count / total_nodes if total_nodes > 0 else 0,
            'text_density': text_count / total_nodes if total_nodes > 0 else 0
        }
    
    def _is_frame_like_geometry(self, component_nodes: List[str], analysis: Dict[str, Any]) -> bool:
        """Check if component has frame-like geometric properties"""
        # For now, use a simple heuristic - components with high line density and low connectivity
        # could be enhanced with actual geometric analysis of line arrangements
        
        # If component is mostly lines with very few connections per node, likely a frame
        if analysis['line_density'] > 0.8:
            # Calculate average degree
            total_degree = 0
            valid_nodes = 0
            
            for node_id in component_nodes:
                if self.graph_service.graph.has_node(node_id):
                    total_degree += self.graph_service.get_degree(node_id)
                    valid_nodes += 1
            
            avg_degree = total_degree / valid_nodes if valid_nodes > 0 else 0
            
            # Frame-like: high line density but low average connectivity (isolated rectangular patterns)
            return avg_degree < 2.5  # Most frame nodes connect to only 1-2 other nodes
        
        return False
    
    def _create_comprehensive_text_elements(self, associated_text_ids: set, symbol_objects: List[Symbol]) -> List[Dict[str, Any]]:
        """
        Create comprehensive text elements section with association information
        """
        comprehensive_text_elements = []
        
        if not self.original_text_elements:
            logger.info("No original text elements available for comprehensive output")
            return comprehensive_text_elements
        
        # Create lookup dictionaries for associations
        line_text_associations = {}  # text_id -> line_id
        symbol_text_associations = {}  # text_id -> symbol_id
        
        # Find text-to-line associations from graph
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and data.get('text_associated'):
                # Extract text that's associated with this line
                associated_text = data['text_associated']
                # Find the text element with this text content
                for orig_elem in self.original_text_elements:
                    if orig_elem.get('text') == associated_text:
                        line_text_associations[orig_elem['id']] = node_id.replace('line-', '')
                        break
        
        # Find text-to-symbol associations from graph
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.SYMBOL and data.get('text_associated'):
                # Extract text that's associated with this symbol
                associated_text = data['text_associated']
                # Find the text element with this text content
                for orig_elem in self.original_text_elements:
                    if orig_elem.get('text') == associated_text:
                        symbol_text_associations[orig_elem['id']] = node_id.replace('symbol-', '')
                        break
        
        # Build comprehensive text elements
        for orig_elem in self.original_text_elements:
            text_id = orig_elem['id']
            
            # Determine association information
            associated_with = None
            association_type = None
            
            if text_id in line_text_associations:
                associated_with = f"line-{line_text_associations[text_id]}"
                association_type = "line"
            elif text_id in symbol_text_associations:
                associated_with = f"symbol-{symbol_text_associations[text_id]}"
                association_type = "symbol"
            else:
                association_type = "standalone"
            
            # Create comprehensive text element
            comprehensive_element = {
                "id": text_id,
                "text": orig_elem['text'],
                "original_bbox": orig_elem['original_bbox'],
                "normalized_bbox": orig_elem['normalized_bbox'],
                "confidence": orig_elem['confidence'],
                "association_type": association_type
            }
            
            # Add association details if associated
            if associated_with:
                comprehensive_element["associated_with"] = associated_with
            
            comprehensive_text_elements.append(comprehensive_element)
        
        logger.info(f"Created comprehensive text elements section with {len(comprehensive_text_elements)} elements")
        return comprehensive_text_elements
    
    def _build_output(self, text_objects: List[TextElement], associated_text_ids: set, symbol_objects: List[Symbol]) -> Dict[str, Any]:
        """Build final output with connections and associations"""
        symbols = []
        lines = []
        junctions = []
        connections = []
        standalone_texts = []
        
        # Extract symbols with text associations
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.SYMBOL:
                symbol_data = {
                    "id": node_id.replace("symbol-", ""),
                    "type": data['label'],
                    "class_name": data.get('class_name'),
                    "bbox": [data['bbox'].topX, data['bbox'].topY, 
                            data['bbox'].bottomX, data['bbox'].bottomY],
                    "connections": self.graph_service.get_neighbors(node_id),
                    "text_associated": data.get('text_associated')
                }
                symbols.append(symbol_data)
            
            elif data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                line_data = {
                    "id": node_id.replace("line-", ""),
                    "points": data['points'],
                    "text_associated": data.get('text_associated'),
                    "connections": self.graph_service.get_neighbors(node_id)
                }
                
                # Add debug information for merged lines
                if data.get('merged_from') and data.get('original_lines_data'):
                    line_data["debug_info"] = {
                        "merged_from": [line_id.replace('line-', '') for line_id in data['merged_from']],
                        "original_lines": data['original_lines_data'],
                        "merge_method": "line_consolidation"
                    }
                
                lines.append(line_data)
            
            elif data['node_type'] == GraphNodeType.JUNCTION:
                junction_data = {
                    "id": node_id.replace("junction-", ""),
                    "point": list(data['point']),  # Convert tuple to list
                    "junction_type": data['junction_type'].value,
                    "connected_lines": data['connected_lines'],
                    "confidence": data['confidence'],
                    "connections": self.graph_service.get_neighbors(node_id)
                }
                junctions.append(junction_data)
        
        # Collect standalone text elements (not associated with any symbols or lines)
        for text_elem in text_objects:
            if text_elem.id not in associated_text_ids:
                standalone_text = {
                    "id": text_elem.id,
                    "text": text_elem.text,
                    "bbox": [text_elem.bbox.topX, text_elem.bbox.topY,
                            text_elem.bbox.bottomX, text_elem.bbox.bottomY],
                    "confidence": text_elem.score
                }
                standalone_texts.append(standalone_text)
                logger.info(f"Added standalone text: '{text_elem.text}'")
        
        # Extract connections
        for edge in self.graph_service.graph.edges():
            connections.append({
                "from": edge[0],
                "to": edge[1]
            })
        
        # Create comprehensive text_elements section with association information
        text_elements = self._create_comprehensive_text_elements(
            associated_text_ids, symbol_objects
        )
        
        # Get connected components
        components = self.graph_service.get_connected_components()
        
        result = {
            "symbols": symbols,
            "lines": lines,
            "junctions": junctions,
            "connections": connections,
            "connected_components": [list(comp) for comp in components],
            "graph_stats": {
                "num_nodes": self.graph_service.graph.number_of_nodes(),
                "num_edges": self.graph_service.graph.number_of_edges(),
                "num_components": len(components),
                "num_junctions": len(junctions)
            }
        }
        
        # Add comprehensive text elements section
        if text_elements:
            result["text_elements"] = text_elements
        
        # Add standalone texts only if there are any
        if standalone_texts:
            result["standalone_texts"] = standalone_texts
        
        # Add component filtering statistics
        if hasattr(self, 'component_filtering_stats'):
            result["component_filtering"] = self.component_filtering_stats
        
        return result
