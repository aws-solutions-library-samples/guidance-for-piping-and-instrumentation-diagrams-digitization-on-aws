"""
Text association logic for P&ID graph processing.
"""

import logging
from typing import List, Dict
from models import Symbol, TextElement, LineSegment
from graph_service import GraphService
from geometry import calculate_bbox_distance, calculate_bbox_edge_distance

logger = logging.getLogger()


class TextAssociator:
    """Handles text-to-symbol and text-to-line association logic"""
    
    def __init__(self, graph_service: GraphService, config: Dict):
        self.graph_service = graph_service
        self.config = config
    
    def associate_text_with_symbols(self, symbols: List[Symbol], text_elements: List[TextElement], 
                                   associated_text_ids: set):
        """Associate remaining text elements with their closest symbols using improved distance calculation"""
        logger.info(f"Starting symbol-text association for {len([t for t in text_elements if t.id not in associated_text_ids])} unassociated text elements")
        
        for text_elem in text_elements:
            if text_elem.id not in associated_text_ids:
                logger.info(f"Processing text element: '{text_elem.text}' at bbox {[text_elem.bbox.topX, text_elem.bbox.topY, text_elem.bbox.bottomX, text_elem.bbox.bottomY]}")
                
                # Find closest symbol using both center-to-center and edge-to-edge distances
                closest_symbol = None
                min_distance = float('inf')
                distances_calculated = []
                
                for symbol in symbols:
                    # Calculate both center-to-center and edge-to-edge distances
                    center_distance = calculate_bbox_distance(text_elem.bbox, symbol.bbox)
                    edge_distance = calculate_bbox_edge_distance(text_elem.bbox, symbol.bbox)
                    
                    # Use the smaller of the two distances (edge distance is usually more accurate)
                    distance = min(center_distance, edge_distance)
                    distances_calculated.append({
                        'symbol_id': symbol.id,
                        'center_dist': center_distance,
                        'edge_dist': edge_distance,
                        'final_dist': distance
                    })
                    
                    if distance < min_distance:
                        min_distance = distance
                        closest_symbol = symbol
                
                # Log distance calculations for debugging
                logger.info(f"Distance calculations for text '{text_elem.text}': {distances_calculated[:3]}")  # Log first 3 for brevity
                logger.info(f"Closest symbol: {closest_symbol.id if closest_symbol else None} at distance: {min_distance}")
                
                # Try association with primary threshold first
                threshold_used = None
                if closest_symbol and min_distance <= self.config["graph_symbol_text_association_threshold"]:
                    threshold_used = "primary"
                # If no match, try fallback threshold
                elif closest_symbol and min_distance <= self.config["graph_symbol_text_fallback_threshold"]:
                    threshold_used = "fallback"
                
                if threshold_used:
                    symbol_node_id = f"symbol-{closest_symbol.id}"
                    symbol_node = self.graph_service.get_node(symbol_node_id)
                    
                    # Add or append to existing text association
                    existing_text = symbol_node.get('text_associated')
                    if existing_text:
                        symbol_node['text_associated'] = f"{existing_text} | {text_elem.text}"
                    else:
                        symbol_node['text_associated'] = text_elem.text
                    
                    associated_text_ids.add(text_elem.id)
                    logger.info(f"Associated text '{text_elem.text}' with symbol {closest_symbol.id} (distance: {min_distance:.1f}, threshold: {threshold_used})")
                else:
                    logger.warning(f"Text '{text_elem.text}' could not be associated with any symbol. Closest distance: {min_distance:.1f}, thresholds: primary={self.config['graph_symbol_text_association_threshold']}, fallback={self.config['graph_symbol_text_fallback_threshold']}")
