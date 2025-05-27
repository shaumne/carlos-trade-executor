def clean_coin_line(self, row_index):
        """Clean up a coin line after successful sell by resetting all relevant fields"""
        try:
            # Fields to reset with specific values
            updates = {
                'Buy Signal': 'WAIT',  # Set to WAIT
                'Tradable': 'YES',     # Set to YES
                'Take Profit': '',
                'Stop-Loss': '',
                'Order Placed?': '',
                'Order Date': '',
                'Purchase Price': '',
                'Quantity': '',
                'Purchase Date': '',
                'Sold?': '',
                'Sell Price': '',
                'Sell Quantity': '',
                'Sold Date': '',
                'Notes': '',
                'order_id': ''         # Clear order_id
            }
            
            # Update all fields
            for field, value in updates.items():
                try:
                    col_index = self.get_column_index_by_name(field)
                    if col_index:
                        self.worksheet.update_cell(row_index, col_index, value)
                        logger.debug(f"Updated {field} to '{value}' at row {row_index}")
                except Exception as e:
                    logger.error(f"Error updating {field} at row {row_index}: {str(e)}")
            
            logger.info(f"Successfully cleaned up coin line at row {row_index}")
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning coin line at row {row_index}: {str(e)}")
            return False 